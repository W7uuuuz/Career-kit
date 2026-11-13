"""阶段 6：目标企业筛选。

只承担一个决策：确定目标企业池。目录筛选、include/exclude/selected_ids 匹配、
计数与确认门禁由代码完成；不抓取、不统计需求。产物 CompanyPool 是下游唯一输入。

selected_ids 是用户显式圈定的企业清单，作为 allowlist 生效且优先于 include：
清单内的企业保留，清单外的企业一律置为 excluded。
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from ...scrapers import catalog
from ...tools.profile import load_profile, save_profile
from ..artifacts.models import ArtifactMeta, CompanyEntry, CompanyPool, TargetSpec
from ..orchestrator import state_machine
from .base import StageContext, StageResult

STAGE_ID = state_machine.STAGE_COMPANY_POOL
TARGET_STAGE_ID = state_machine.STAGE_TARGET
REQUIRES = ("target_spec",)
PRODUCES = "company_pool"

DEFAULT_TARGET_TIERS: tuple[str, ...] = ("大厂",)
DEFAULT_BRIDGE_TIERS: tuple[str, ...] = ("中厂",)
DEFAULT_INDUSTRY = "互联网"

_TOKEN_SPLIT_RE = re.compile(r"[,，、;；\s]+")


def parse_tokens(value: Any) -> list[str]:
    """把 include/exclude 或档位参数解析为去重后的 token 列表。

    支持 JSON 数组、逗号/顿号/分号/空白分隔；按小写去重并保留首次出现顺序。
    """
    raw_items: list[Any] = []
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        parsed: Any = None
        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except (json.JSONDecodeError, TypeError):
                parsed = None
        raw_items = parsed if isinstance(parsed, list) else _TOKEN_SPLIT_RE.split(text)
    elif isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    else:
        return []

    tokens: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        token = str(item).strip()
        if not token:
            continue
        key = token.lower()
        if key in seen:
            continue
        seen.add(key)
        tokens.append(token)
    return tokens


def run(ctx: StageContext, inputs: dict[str, Any]) -> StageResult:
    """执行阶段 6：生成并保存 CompanyPool，按确认状态决定是否推进。"""
    store = ctx.store
    target_spec_id, target_error = _resolve_target_spec_id(
        store, ctx.profile_name, inputs
    )
    if target_error:
        return StageResult(
            status="failed",
            message=target_error,
            next_stage=STAGE_ID,
        )

    spec, spec_error = _resolve_spec(
        store, ctx.profile_name, target_spec_id, inputs
    )
    if spec_error:
        return StageResult(
            status="failed",
            message=spec_error,
            next_stage=STAGE_ID,
        )
    industry = str(inputs.get("industry") or DEFAULT_INDUSTRY).strip()
    selected_tokens = parse_tokens(inputs.get("selected_ids"))
    companies, gaps = _build_entries(
        spec,
        industry,
        parse_tokens(inputs.get("include")),
        parse_tokens(inputs.get("exclude")),
        selected_tokens,
    )
    tier_problems = _tier_consistency_problems(spec, companies)
    if tier_problems:
        return StageResult(
            status="failed",
            message="目标档位与企业池不一致，拒绝写入 CompanyPool："
            + "；".join(tier_problems),
            next_stage=STAGE_ID,
        )
    selected = [entry for entry in companies if entry.status != "excluded"]
    # allowlist 生效时，落库的 selected_ids 是命中企业的目录 id；未传时为空。
    selected_ids = [entry.id for entry in selected] if selected_tokens else []
    confirmed = _requested_confirmation(ctx, inputs)
    effective_confirmed = confirmed and bool(selected)
    if confirmed:
        for entry in selected:
            entry.status = "confirmed"

    baseline_plan_id = _resolve_baseline_plan_id(store, ctx.profile_name)
    meta = ArtifactMeta(
        id=store.new_id("cp_"),
        stage=STAGE_ID,
        profile_name=ctx.profile_name,
        created_at=datetime.now().isoformat(),
        inputs=_meta_inputs(
            inputs,
            spec,
            industry,
            confirmed,
            target_spec_id=target_spec_id,
            baseline_plan_id=baseline_plan_id,
            selected_tokens=selected_tokens,
        ),
        validation={
            "confirmed": effective_confirmed,
            "requested_confirmed": confirmed,
            "selected": len(selected),
            "selected_ids": selected_ids,
        },
    )
    pool = CompanyPool(
        meta=meta,
        target_spec=spec,
        companies=companies,
        counts=_counts(companies),
        gaps=gaps,
    )
    artifact_id = store.save(pool)

    if confirmed and not effective_confirmed:
        return StageResult(
            status="insufficient_data",
            artifact_id=artifact_id,
            message="没有可确认的目标企业：请调整档位、行业或 include/exclude 后重试。",
            next_stage=STAGE_ID,
            warnings=gaps,
        )
    if not confirmed:
        return StageResult(
            status="needs_confirmation",
            artifact_id=artifact_id,
            message=f"已生成 {len(selected)} 家推荐企业，等待用户确认后才能进入证据采集。",
            next_stage=STAGE_ID,
            warnings=gaps,
        )

    _update_core_state(ctx.profile_name, artifact_id)
    return StageResult(
        status="ok",
        artifact_id=artifact_id,
        message=f"已确认 {len(selected)} 家目标企业。",
        next_stage=state_machine.STAGE_EVIDENCE,
        warnings=gaps,
    )


def validate(artifact: BaseModel) -> list[str]:
    """校验 CompanyPool：阶段一致、企业字段完整、确认状态自洽。"""
    if not isinstance(artifact, CompanyPool):
        return ["artifact 必须是 CompanyPool"]

    problems: list[str] = []
    if artifact.meta.stage != STAGE_ID:
        problems.append(f"meta.stage 应为 {STAGE_ID}，实际为 {artifact.meta.stage}")

    seen: set[str] = set()
    for entry in artifact.companies:
        key = entry.id.strip().lower()
        if not key:
            problems.append("存在空 id 的企业条目")
            continue
        if key in seen:
            problems.append(f"企业 id 重复：{entry.id}")
        seen.add(key)
        if not entry.name.strip():
            problems.append(f"企业 {entry.id} 缺少 name")
        if entry.status != "excluded" and not entry.tier:
            problems.append(f"企业 {entry.id} 缺少 tier")

    confirmed = artifact.meta.validation.get("confirmed") is True
    confirmed_entries = [entry for entry in artifact.companies if entry.status == "confirmed"]
    if confirmed and not confirmed_entries:
        problems.append("confirmed=true 但没有任何 confirmed 企业")
    if not confirmed and confirmed_entries:
        problems.append("confirmed=false 但存在 confirmed 企业")
    if confirmed and any(entry.status == "recommended" for entry in artifact.companies):
        problems.append("confirmed=true 但仍有企业状态为 recommended")
    return problems


def _target_spec_from_inputs(inputs: dict[str, Any]) -> TargetSpec:
    raw = inputs.get("target_spec")
    if isinstance(raw, TargetSpec):
        spec = raw.model_copy(deep=True)
    elif isinstance(raw, BaseModel):
        spec = TargetSpec.model_validate(raw.model_dump())
    elif isinstance(raw, dict):
        spec = TargetSpec.model_validate(raw)
    else:
        spec = TargetSpec()

    spec.target_tiers = (
        parse_tokens(inputs.get("target_tiers")) or spec.target_tiers or list(DEFAULT_TARGET_TIERS)
    )
    spec.bridge_tiers = (
        parse_tokens(inputs.get("bridge_tiers")) or spec.bridge_tiers or list(DEFAULT_BRIDGE_TIERS)
    )
    city = str(inputs.get("city") or "").strip()
    role = str(inputs.get("role") or "").strip()
    if city:
        spec.city = city
    if role:
        spec.role = role
    return spec


def _resolve_spec(
    store: Any,
    profile_name: str,
    target_spec_id: str,
    inputs: dict[str, Any],
) -> tuple[TargetSpec, str]:
    """解析唯一的有效 TargetSpec（显式入参 > 档案推断 > 默认值）。

    - 有 target_spec_id 时，以 artifact 为基准，但显式身份字段与档案推断只能
      填充 artifact 的空字段；双方均有值且冲突时拒绝生成；
    - target_tiers / bridge_tiers 是显式筛选参数，始终优先于 artifact 与档案；
    - 没有 target_spec_id 时直接由档案/输入构造。

    返回的 TargetSpec 同时驱动回显、分档统计、企业池与 artifact 写入。
    """
    inferred = _target_spec_from_inputs(inputs)
    artifact_spec = _load_target_spec(store, profile_name, target_spec_id)
    if target_spec_id and artifact_spec is None:
        return (
            TargetSpec(),
            f"TargetSpec「{target_spec_id}」不存在、类型不符或不属于当前档案",
        )
    if artifact_spec is None:
        return inferred, ""

    conflicts = _target_conflicts(inputs, artifact_spec)
    if conflicts:
        return (
            TargetSpec(),
            "目标定位与 target_spec_id 指向的 TargetSpec 冲突，拒绝落库："
            + "；".join(conflicts)
            + "。请统一 role/city/direction 等身份字段，或改用匹配的 target_spec_id。",
        )
    return _merge_target_spec(artifact_spec, inferred, inputs), ""


def _merge_target_spec(
    artifact_spec: TargetSpec,
    inferred: TargetSpec,
    inputs: dict[str, Any],
) -> TargetSpec:
    """把显式参数与档案推断合并进 artifact 基准，保持单一事实源。"""
    spec = artifact_spec.model_copy(deep=True)
    for field in ("direction", "role", "city", "graduation_year", "job_kind"):
        if not getattr(spec, field):
            setattr(spec, field, getattr(inferred, field))
    if not spec.constraints:
        spec.constraints = list(inferred.constraints)
    if not spec.exclude_directions:
        spec.exclude_directions = list(inferred.exclude_directions)

    explicit_target = parse_tokens(inputs.get("target_tiers"))
    explicit_bridge = parse_tokens(inputs.get("bridge_tiers"))
    spec.target_tiers = (
        explicit_target
        or spec.target_tiers
        or inferred.target_tiers
        or list(DEFAULT_TARGET_TIERS)
    )
    spec.bridge_tiers = (
        explicit_bridge
        or spec.bridge_tiers
        or inferred.bridge_tiers
        or list(DEFAULT_BRIDGE_TIERS)
    )
    return spec


def _load_target_spec(
    store: Any, profile_name: str, target_spec_id: str
) -> TargetSpec | None:
    if not target_spec_id:
        return None
    data = store.load(target_spec_id)
    if not _is_target_spec(data, profile_name):
        return None
    fields = {name: data[name] for name in TargetSpec.model_fields if name in data}
    try:
        return TargetSpec.model_validate(fields)
    except Exception:  # noqa: BLE001 - 损坏 artifact 按不一致处理
        return None


def _target_conflicts(
    inputs: dict[str, Any],
    artifact_spec: TargetSpec,
) -> list[str]:
    """调用方显式给出的身份字段与 artifact 的非空值不一致时报告冲突。

    artifact 为空字段表示「尚未确定」，不构成冲突；显式参数与档案推断会
    在合并阶段填充它。target_tiers / bridge_tiers 是可调整筛选参数，不参与
    身份冲突判断。
    """
    supplied: dict[str, Any] = {}
    raw = inputs.get("target_spec")
    if isinstance(raw, BaseModel):
        raw = raw.model_dump()
    if isinstance(raw, dict):
        supplied.update(raw)
    for field in ("role", "city", "direction", "graduation_year"):
        value = str(inputs.get(field) or "").strip()
        if value:
            supplied[field] = value

    identity_fields = (
        "direction",
        "role",
        "city",
        "graduation_year",
        "job_kind",
        "constraints",
    )
    conflicts: list[str] = []
    for field in identity_fields:
        if field not in supplied:
            continue
        value = _normalize_target_field(supplied.get(field))
        current = _normalize_target_field(getattr(artifact_spec, field))
        if not value or not current:
            continue
        if not _target_field_compatible(field, value, current):
            conflicts.append(
                f"{_FIELD_LABELS.get(field, field)} 当前为 {current!r}，"
                f"显式传入 {value!r}"
            )
    return conflicts


# 岗位/方向常见后缀：只用于判断“同一方向的不同写法”，不改变落库原值。
_ROLE_SUFFIXES = (
    "开发工程师",
    "研发工程师",
    "算法工程师",
    "工程师",
    "实习生",
    "实习",
    "岗位",
    "职位",
    "专员",
    "方向",
)
_ROLE_SEPARATOR_RE = re.compile(r"[\s\-_/·,，、()（）]+")
_YEAR_RE = re.compile(r"(19|20)\d{2}")


def _normalize_text_key(value: str) -> str:
    text = _ROLE_SEPARATOR_RE.sub("", value.strip().lower())
    text = text.replace("市", "") if text.endswith("市") else text
    for suffix in _ROLE_SUFFIXES:
        if text.endswith(suffix) and len(text) > len(suffix):
            text = text[: -len(suffix)]
            break
    return text


def _target_field_compatible(field: str, value: Any, current: Any) -> bool:
    """身份字段是否可视为同一目标（兼容后缀、空格与包含关系）。"""
    if field == "constraints":
        return value == current
    if field == "graduation_year":
        value_year = _YEAR_RE.search(str(value))
        current_year = _YEAR_RE.search(str(current))
        if value_year and current_year:
            return value_year.group() == current_year.group()
        return str(value).strip() == str(current).strip()
    if not isinstance(value, str) or not isinstance(current, str):
        return value == current

    left = _normalize_text_key(value)
    right = _normalize_text_key(current)
    if not left or not right:
        return False
    if left == right:
        return True
    # 「Agent 开发」与「AI Agent 开发」这类包含关系视为同方向；
    # 过短的关键词（如「开发」）不足以判定为同一目标，仍按冲突处理。
    shorter, longer = sorted((left, right), key=len)
    return len(shorter) >= 3 and shorter in longer


_FIELD_LABELS = {
    "direction": "目标方向",
    "role": "目标岗位 role",
    "city": "目标城市 city",
    "graduation_year": "毕业年份 graduation_year",
    "job_kind": "招聘类型 job_kind",
    "constraints": "约束条件 constraints",
}


def _normalize_target_field(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    if value is None:
        return ""
    return value


def _requested_confirmation(ctx: StageContext, inputs: dict[str, Any]) -> bool:
    if "confirmed" in inputs:
        return _as_bool(inputs.get("confirmed"))
    return bool(ctx.user_confirmed)


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "是", "确认"}
    if isinstance(value, (int, float)):
        return bool(value)
    return False


def _build_entries(
    spec: TargetSpec,
    industry: str,
    include_tokens: list[str],
    exclude_tokens: list[str],
    selected_tokens: list[str] | None = None,
) -> tuple[list[CompanyEntry], list[str]]:
    tiers = _dedupe([*spec.target_tiers, *spec.bridge_tiers])
    items = catalog.list_companies(tier=tiers, industry=industry)
    entries: dict[str, CompanyEntry] = {
        str(item["id"]).lower(): _entry(item, _tier_reason(str(item["tier"]), spec)) for item in items
    }
    gaps: list[str] = []

    included, missing_include = _resolve_tokens(include_tokens)
    for _token, item in included:
        key = str(item["id"]).lower()
        if key in entries:
            entries[key].reason = "用户 include 指定"
        else:
            entries[key] = _entry(item, "用户 include 指定")
    include_keys = {str(item["id"]).lower() for _token, item in included}

    excluded, missing_exclude = _resolve_tokens(exclude_tokens)
    for _token, item in excluded:
        key = str(item["id"]).lower()
        if key in include_keys:
            continue
        if key in entries:
            entries[key].status = "excluded"
            entries[key].reason = "用户 exclude 排除"

    # selected_ids 是 allowlist：优先于 include，清单外的企业一律排除。
    selected_tokens = selected_tokens or []
    selected_resolved, missing_selected = _resolve_tokens(selected_tokens)
    selected_keys = {str(item["id"]).lower() for _token, item in selected_resolved}
    for _token, item in selected_resolved:
        key = str(item["id"]).lower()
        if key not in entries:
            entries[key] = _entry(item, "用户 selected_ids 指定")
    if selected_keys:
        allowlist_reason = "未在用户选择清单内（selected_ids）"
        for key, entry in entries.items():
            if key in selected_keys or entry.status == "excluded":
                continue
            entry.status = "excluded"
            entry.reason = allowlist_reason

    if missing_include:
        gaps.append(f"include 未收录（目录中不存在）：{'、'.join(missing_include)}")
    if missing_exclude:
        gaps.append(f"exclude 未收录（目录中不存在）：{'、'.join(missing_exclude)}")
    if missing_selected:
        gaps.append(f"selected_ids 未收录：{'、'.join(missing_selected)}")

    companies = sorted(entries.values(), key=lambda entry: (-catalog.tier_rank(entry.tier), entry.name))
    selected = [entry for entry in companies if entry.status != "excluded"]
    if not selected:
        gap_tiers = "、".join(tiers) or "不限"
        gaps.append(f"目录中没有匹配目标档位（{gap_tiers}）与行业「{industry}」的企业")

    unscrapable = [entry.name for entry in selected if not entry.scrapable]
    if unscrapable:
        gaps.append(f"未接入自动抓取（需手动投递或后续补充 scraper）：{'、'.join(unscrapable)}")
    return companies, gaps


def _resolve_tokens(
    tokens: list[str],
) -> tuple[list[tuple[str, dict[str, Any]]], list[str]]:
    resolved: list[tuple[str, dict[str, Any]]] = []
    missing: list[str] = []
    for token in tokens:
        item = catalog.get_company(token)
        if item is None:
            missing.append(token)
        else:
            resolved.append((token, item))
    return resolved, missing


def _entry(item: dict[str, Any], reason: str) -> CompanyEntry:
    return CompanyEntry(
        id=str(item.get("id") or ""),
        name=str(item.get("name") or ""),
        tier=str(item.get("tier") or "未收录"),
        industry=str(item.get("industry") or ""),
        scrapable=bool(item.get("scrapable")),
        scrapers=[str(scraper) for scraper in item.get("available_scrapers") or []],
        careers_url=str(item.get("careers_url") or ""),
        reason=reason,
    )


def _tier_reason(tier: str, spec: TargetSpec) -> str:
    in_target = tier in spec.target_tiers
    in_bridge = tier in spec.bridge_tiers
    if in_target and in_bridge:
        return f"目标与桥接档位「{tier}」"
    if in_target:
        return f"目标档位「{tier}」"
    if in_bridge:
        return f"桥接档位「{tier}」"
    return f"目录档位「{tier}」"


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _tier_consistency_problems(
    spec: TargetSpec, companies: list[CompanyEntry]
) -> list[str]:
    """确认企业池档位来自同一份 TargetSpec，避免 target 与 counts 口径不一致。"""
    allowed = set(spec.target_tiers) | set(spec.bridge_tiers)
    problems: list[str] = []
    for entry in companies:
        if entry.status == "excluded" or entry.tier in allowed:
            continue
        # 用户显式 include / selected_ids 指定的企业不受档位过滤限制。
        if "include" in entry.reason or "selected" in entry.reason:
            continue
        expected = "、".join(spec.target_tiers + spec.bridge_tiers) or "不限"
        problems.append(
            f"企业「{entry.name}」的档位为 {entry.tier!r}，"
            f"但目标/桥接档位为 {expected}；请调整 target_tiers/bridge_tiers 后重试"
        )
    return problems


def _counts(companies: list[CompanyEntry]) -> dict[str, int]:
    counts: dict[str, int] = {
        "total": 0,
        "confirmed": 0,
        "recommended": 0,
        "excluded": 0,
        "scrapable": 0,
        "not_scrapable": 0,
    }
    for entry in companies:
        if entry.status == "excluded":
            counts["excluded"] += 1
            continue
        counts["total"] += 1
        counts[entry.status] = counts.get(entry.status, 0) + 1
        counts["scrapable" if entry.scrapable else "not_scrapable"] += 1
        tier_key = f"tier:{entry.tier or '未收录'}"
        counts[tier_key] = counts.get(tier_key, 0) + 1
    return counts


def _resolve_target_spec_id(
    store: Any, profile_name: str, inputs: dict[str, Any]
) -> tuple[str, str]:
    """解析 target_spec_id：显式 id 校验归属，空 id 读 core_state 或 latest。"""
    explicit = str(inputs.get("target_spec_id") or "").strip()
    if explicit:
        data = store.load(explicit)
        if not _is_target_spec(data, profile_name):
            return "", f"TargetSpec「{explicit}」不存在、类型不符或不属于当前档案"
        return explicit, ""

    core_id = _core_state_target_spec_id(profile_name)
    if core_id:
        data = store.load(core_id)
        if _is_target_spec(data, profile_name):
            return core_id, ""

    latest = store.latest(profile_name, TARGET_STAGE_ID)
    if _is_target_spec(latest, profile_name):
        meta = latest.get("meta") if isinstance(latest.get("meta"), dict) else {}
        return str(meta.get("id") or ""), ""
    return "", ""


def _core_state_target_spec_id(profile_name: str) -> str:
    try:
        profile = load_profile(profile_name)
    except Exception:  # noqa: BLE001 - 档案读取失败时按无 core_state 处理
        return ""
    core_state = getattr(profile, "core_state", None)
    if not isinstance(core_state, dict):
        return ""
    return str(core_state.get("target_spec_id") or "").strip()


def _is_target_spec(data: Any, profile_name: str) -> bool:
    if not isinstance(data, dict):
        return False
    meta = data.get("meta")
    if not isinstance(meta, dict):
        return False
    return (
        meta.get("stage") == TARGET_STAGE_ID
        and str(meta.get("profile_name") or "") == profile_name
    )


def _resolve_baseline_plan_id(store: Any, profile_name: str) -> str:
    """CompanyPool 的上游是 BaselinePlan；缺失时留空，由 progress 阻止推进。"""
    core_id = _core_state_key(profile_name, "baseline_plan_id")
    if core_id:
        data = store.load(core_id)
        if _is_stage(data, state_machine.STAGE_BASELINE_PLAN, profile_name):
            return core_id
    latest = store.latest(profile_name, state_machine.STAGE_BASELINE_PLAN)
    if _is_stage(latest, state_machine.STAGE_BASELINE_PLAN, profile_name):
        meta = latest.get("meta") if isinstance(latest.get("meta"), dict) else {}
        return str(meta.get("id") or "")
    return ""


def _core_state_key(profile_name: str, key: str) -> str:
    try:
        profile = load_profile(profile_name)
    except Exception:  # noqa: BLE001 - 档案读取失败时按无 core_state 处理
        return ""
    core_state = getattr(profile, "core_state", None)
    if not isinstance(core_state, dict):
        return ""
    return str(core_state.get(key) or "").strip()


def _is_stage(data: Any, stage: str, profile_name: str) -> bool:
    if not isinstance(data, dict):
        return False
    meta = data.get("meta")
    if not isinstance(meta, dict):
        return False
    return meta.get("stage") == stage and str(
        meta.get("profile_name") or ""
    ) == profile_name


def _meta_inputs(
    inputs: dict[str, Any],
    spec: TargetSpec,
    industry: str,
    confirmed: bool,
    *,
    target_spec_id: str = "",
    baseline_plan_id: str = "",
    selected_tokens: list[str] | None = None,
) -> dict[str, str]:
    return {
        "target_spec_id": target_spec_id,
        "baseline_plan_id": baseline_plan_id,
        "target_tiers": "、".join(spec.target_tiers),
        "bridge_tiers": "、".join(spec.bridge_tiers),
        "city": spec.city,
        "role": spec.role,
        "industry": industry,
        "include": _stringify(inputs.get("include")),
        "exclude": _stringify(inputs.get("exclude")),
        "selected_ids": ",".join(selected_tokens or []),
        "confirmed": "true" if confirmed else "false",
    }


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple, set)):
        return "、".join(str(item) for item in value)
    return str(value)


def _update_core_state(profile_name: str, artifact_id: str) -> None:
    profile = load_profile(profile_name)
    core_state = dict(profile.core_state or {})
    core_state.update(
        {
            "company_pool_id": artifact_id,
            "stage": STAGE_ID,
            "updated_at": datetime.now().isoformat(),
        }
    )
    profile.core_state = core_state
    save_profile(profile, profile_name)


__all__ = [
    "DEFAULT_BRIDGE_TIERS",
    "DEFAULT_INDUSTRY",
    "DEFAULT_TARGET_TIERS",
    "PRODUCES",
    "REQUIRES",
    "STAGE_ID",
    "parse_tokens",
    "run",
    "validate",
]
