"""Core v2 阶段 8：企业需求分析。

统计与解读严格分离：
- 关键词命中按「提及该词的 JD/面经条数」计频，不按出现次数；
- 公司覆盖按 company_id（缺省用公司名）去重；
- Wilson 95% 区间只做比例区间估计，纯公式计算；
- 学历/经验逐条 JD 抽取，不聚合为全局结论；
- LLM 只能填写 interpretation，保存时用代码重新计算并校验。
"""

from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from ...education import normalize_education_tag
from ...research_digest import _KEYWORD_GROUPS
from ...tools.profile import load_profile, save_profile
from ..artifacts.models import (
    ArtifactMeta,
    EvidenceRun,
    HardRequirement,
    InterviewEvidence,
    JDEvidence,
    RequirementItem,
    RequirementProfile,
)
from ..orchestrator import state_machine
from .base import StageContext, StageResult, clean_evidence_ids

STAGE_ID = state_machine.STAGE_REQUIREMENT
REQUIRES = ("evidence_run",)
PRODUCES = "requirement_profile"

INTERPRETATION_KEYS = ("summary", "priorities", "company_notes", "risks", "notes")

# 不依赖词边界：中文紧邻（如「参考JD999」）与大小写混写都要识别。
_EVIDENCE_TOKEN_PATTERN = re.compile(r"(?i)(?:jd|iv)\d+")

_WILSON_Z = 1.96
_TOLERANCE = 1e-6
_CI_TOLERANCE = 1e-3

# 只匹配 1-2 位数字，负向后顾避免把「2026年」截成「26年」。
_EXPERIENCE_PATTERN = re.compile(
    r"(?<!\d)(\d{1,2}(?:\.\d+)?)\s*(?:[-~–至到]\s*(\d{1,2}(?:\.\d+)?)\s*)?"
    r"年(?:及)?(?:以上)?(?:相关|工作|开发|从业|项目)?(?:经验)?"
)

# 单条证据的统计输入：evidence_id、company_key、company_label、tier
_Hit = tuple[str, str, str, str]

_DEGREE_RANK = {"专科": 0, "本科": 1, "硕士": 2, "博士": 3}
_USER_EXPERIENCE_KEYS = (
    "experience_years",
    "work_years",
    "years_of_experience",
    "工作经验",
    "经验年限",
)
_GRADUATION_KEYS = ("graduation_year", "graduation", "届别")
_PREFERRED_DEGREE_RE = re.compile(
    r"[^，。；;\n]*(?:优先|加分)[^，。；;\n]*"
)


def wilson_interval(
    count: int, total: int, z: float = _WILSON_Z
) -> tuple[float | None, float | None]:
    """Wilson 95% 区间（比例），total 为 0 或参数非法时返回 (None, None)。"""
    if total <= 0 or count < 0 or count > total:
        return None, None
    p = count / total
    denominator = 1.0 + z * z / total
    center = (p + z * z / (2.0 * total)) / denominator
    margin = (
        z * math.sqrt(p * (1.0 - p) / total + z * z / (4.0 * total * total))
        / denominator
    )
    low = max(0.0, center - margin)
    high = min(1.0, center + margin)
    return round(low, 4), round(high, 4)


def _jd_text(item: JDEvidence) -> str:
    return " ".join((item.title, item.description, item.requirements, item.summary))


def _interview_text(item: InterviewEvidence) -> str:
    parts = [item.title, item.content, " ".join(item.highlights)]
    return " ".join(parts)


def _company_key(company_id: str, company: str) -> str:
    return (company_id or "").strip() or (company or "").strip() or "未知公司"


def _company_label(company_id: str, company: str) -> str:
    return (company or "").strip() or (company_id or "").strip() or "未知公司"


def _make_item(
    term: str,
    category: str,
    hits: list[_Hit],
    sample_size: int,
    total_companies: int,
) -> RequirementItem:
    companies: list[str] = []
    seen: set[str] = set()
    tier_breakdown: dict[str, int] = {}
    for _evidence_id, company_key, company_label, tier in hits:
        if company_key not in seen:
            seen.add(company_key)
            companies.append(company_label)
        tier_key = tier or "未知"
        tier_breakdown[tier_key] = tier_breakdown.get(tier_key, 0) + 1
    low, high = wilson_interval(len(hits), sample_size)
    return RequirementItem(
        term=term,
        category=category,
        jd_count=len(hits),
        jd_frequency=round(len(hits) / sample_size, 4) if sample_size else 0.0,
        company_count=len(seen),
        company_frequency=round(len(seen) / total_companies, 4) if total_companies else 0.0,
        companies=companies,
        evidence_ids=[hit[0] for hit in hits],
        ci_low=low,
        ci_high=high,
        tier_breakdown=dict(sorted(tier_breakdown.items())),
    )


def _jd_keyword_analysis(
    jd_items: list[JDEvidence],
) -> tuple[list[RequirementItem], list[RequirementItem], list[RequirementItem]]:
    # 缺 requirements 的 JD 单独标记，不进入关键词分母；若全缺则退回全量并保留 gap 提示。
    keyword_ready = [item for item in jd_items if (item.requirements or "").strip()]
    items_for_keywords = keyword_ready or jd_items
    sample_size = len(items_for_keywords)
    total_companies = len({_company_key(i.company_id, i.company) for i in items_for_keywords})
    high_frequency: list[RequirementItem] = []
    nice_to_have: list[RequirementItem] = []
    company_specific: list[RequirementItem] = []

    for category, words in _KEYWORD_GROUPS.items():
        for word in words:
            needle = word.lower()
            hits: list[_Hit] = []
            by_company: dict[str, list[_Hit]] = {}
            for item in items_for_keywords:
                if needle not in _jd_text(item).lower():
                    continue
                hit = (
                    item.id,
                    _company_key(item.company_id, item.company),
                    _company_label(item.company_id, item.company),
                    item.tier,
                )
                hits.append(hit)
                by_company.setdefault(hit[1], []).append(hit)
            if not hits:
                continue

            item_stat = _make_item(word, category, hits, sample_size, total_companies)
            if item_stat.jd_frequency >= 0.5 and item_stat.company_count >= 2:
                high_frequency.append(item_stat)
            elif item_stat.jd_count >= 2:
                nice_to_have.append(item_stat)

            if item_stat.company_count <= 2:
                for company_hits in by_company.values():
                    if len(company_hits) < 2:
                        continue
                    label = company_hits[0][2]
                    company_specific.append(
                        _make_item(
                            f"{word}（{label}）",
                            category,
                            company_hits,
                            sample_size,
                            total_companies,
                        )
                    )

    high_frequency.sort(key=lambda x: (-x.jd_count, -x.company_count, x.term))
    nice_to_have.sort(
        key=lambda x: (-(x.company_count / x.jd_count), -x.jd_count, x.term)
    )
    company_specific.sort(key=lambda x: (-x.jd_count, x.term))
    return high_frequency, nice_to_have, company_specific


def _interview_keyword_analysis(
    interview_items: list[InterviewEvidence],
    tier_by_company: dict[str, str],
) -> list[RequirementItem]:
    sample_size = len(interview_items)
    total_companies = len(
        {_company_key(i.company_id, i.company) for i in interview_items}
    )
    topics: list[RequirementItem] = []
    for category, words in _KEYWORD_GROUPS.items():
        for word in words:
            needle = word.lower()
            hits: list[_Hit] = []
            for item in interview_items:
                if needle not in _interview_text(item).lower():
                    continue
                company_key = _company_key(item.company_id, item.company)
                hits.append(
                    (
                        item.id,
                        company_key,
                        _company_label(item.company_id, item.company),
                        tier_by_company.get(company_key, ""),
                    )
                )
            if hits:
                topics.append(
                    _make_item(word, category, hits, sample_size, total_companies)
                )
    topics.sort(key=lambda x: (-x.jd_count, -x.company_count, x.term))
    return topics


def _extract_experience(text: str) -> str:
    tokens: list[str] = []
    for match in _EXPERIENCE_PATTERN.finditer(text):
        token = re.sub(r"\s+", "", match.group(0))
        if token and token not in tokens:
            tokens.append(token)
    for label in ("应届", "实习"):
        if label in text and label not in tokens:
            tokens.append(label)
    return "；".join(tokens)


def _profile_sections(profile: Any) -> list[dict[str, Any]]:
    if profile is None:
        return []
    return [
        section
        for section in (
            getattr(profile, "who", None),
            getattr(profile, "have", None),
            getattr(profile, "want", None),
        )
        if isinstance(section, dict)
    ]


def _parse_year(value: Any) -> int | None:
    match = re.search(r"(20\d{2}|\d{2})", str(value or ""))
    if not match:
        return None
    year = int(match.group(1))
    return year + 2000 if year < 100 else year


def _user_experience_years(profile: Any) -> float | None:
    for section in _profile_sections(profile):
        for key in _USER_EXPERIENCE_KEYS:
            value = section.get(key)
            if value is None or value == "":
                continue
            if isinstance(value, (int, float)):
                return max(float(value), 0.0)
            text = str(value)
            if "应届" in text or "无经验" in text:
                return 0.0
            match = _EXPERIENCE_PATTERN.search(text)
            if match:
                return max(float(match.group(1)), 0.0)
    for section in _profile_sections(profile):
        for key in ("identity", "status", "tag"):
            text = str(section.get(key) or "")
            if any(word in text for word in ("学生", "在校", "应届")):
                return 0.0
    return None


def _graduation_year(profile: Any) -> int | None:
    for section in _profile_sections(profile):
        for key in _GRADUATION_KEYS:
            year = _parse_year(section.get(key))
            if year is not None:
                return year
    return None


def _user_gate(profile: Any) -> dict[str, Any]:
    if profile is None:
        return {"degree": "", "experience_years": None, "missing": []}
    education_parts: list[str] = []
    for section in _profile_sections(profile):
        for key in ("education", "education_tag", "degree", "tier"):
            value = str(section.get(key) or "").strip()
            if value:
                education_parts.append(value)
    degree = normalize_education_tag(" ".join(education_parts))["degree"]
    experience = _user_experience_years(profile)
    graduation = _graduation_year(profile)
    if experience is None and graduation is not None and graduation >= datetime.now().year:
        experience = 0.0
    missing: list[str] = []
    if not degree:
        missing.append("学历")
    if experience is None:
        missing.append("经验/届别")
    return {"degree": degree, "experience_years": experience, "missing": missing}


def _required_degree(text: str) -> str:
    cleaned = _PREFERRED_DEGREE_RE.sub(" ", text)
    return normalize_education_tag(cleaned)["degree"]


def _required_experience_years(text: str) -> float | None:
    values = [float(match.group(1)) for match in _EXPERIENCE_PATTERN.finditer(text)]
    if values:
        return max(values)
    if "应届" in text or "实习" in text:
        return 0.0
    return None


def _hard_gate_reason(item: JDEvidence, gate: dict[str, Any]) -> str:
    text = " ".join((item.title, item.description, item.requirements))
    required_degree = _required_degree(text)
    user_degree = str(gate.get("degree") or "")
    if (
        required_degree
        and user_degree
        and _DEGREE_RANK.get(required_degree, -1) > _DEGREE_RANK.get(user_degree, -1)
    ):
        return f"JD 要求{required_degree}，高于用户{user_degree}"
    required_experience = _required_experience_years(text)
    user_experience = gate.get("experience_years")
    if (
        required_experience is not None
        and user_experience is not None
        and required_experience > float(user_experience) + _TOLERANCE
    ):
        return (
            f"JD 要求{required_experience:g}年经验，"
            f"用户{float(user_experience):g}年"
        )
    return ""


def _apply_hard_gate(
    jd_items: list[JDEvidence], profile: Any
) -> tuple[list[JDEvidence], list[dict[str, Any]], list[str]]:
    gate = _user_gate(profile)
    kept: list[JDEvidence] = []
    excluded: list[dict[str, Any]] = []
    for item in jd_items:
        reason = _hard_gate_reason(item, gate)
        if not reason:
            kept.append(item)
            continue
        excluded.append(
            {
                "evidence_id": item.id,
                "company": item.company or item.company_id,
                "title": item.title,
                "reason": reason,
            }
        )
    gaps: list[str] = []
    if excluded:
        samples = "、".join(
            f"{entry['evidence_id']} {entry['title']}（{entry['reason']}）"
            for entry in excluded[:10]
        )
        if len(excluded) > 10:
            samples += " 等"
        gaps.append(
            f"硬门槛预筛剔除 {len(excluded)} 条 JD，不进入高频词统计；样本：{samples}"
        )
    if profile is not None and gate["missing"]:
        gaps.append(
            "档案缺少" + "、".join(gate["missing"]) + "字段，对应硬门槛未预筛（不猜测）"
        )
    return kept, excluded, gaps


def _extract_hard_requirements(jd_items: list[JDEvidence]) -> list[HardRequirement]:
    results: list[HardRequirement] = []
    for item in jd_items:
        text = " ".join((item.title, item.description, item.requirements))
        education_info = normalize_education_tag(text)
        education = (
            education_info["tag"]
            or education_info["degree"]
            or education_info["tier"]
        )
        experience = _extract_experience(text)
        if not education and not experience:
            continue
        note = "JD 详情不完整，硬门槛可能缺失" if item.detail_status != "ok" else ""
        results.append(
            HardRequirement(
                evidence_id=item.id,
                company=item.company or item.company_id,
                title=item.title,
                education=education,
                experience=experience,
                note=note,
            )
        )
    results.sort(key=lambda x: x.evidence_id)
    return results


def _confidence(sample: int, medium_at: int, high_at: int) -> str:
    if sample >= high_at:
        return "high"
    if sample >= medium_at:
        return "medium"
    return "low"


def _build_gaps(
    run: EvidenceRun,
    jd_items: list[JDEvidence],
    hard_gate_gaps: list[str],
) -> list[str]:
    jd_sample = len(jd_items)
    interview_sample = len(run.interview_items)
    gaps: list[str] = []

    if jd_sample == 0:
        gaps.append("本批次没有可用 JD 样本，无法形成需求画像")
    elif jd_sample < 15:
        gaps.append(
            f"JD 样本仅 {jd_sample} 条（<15），统计置信度低，结论只能作方向参考"
        )

    missing_requirements = sum(
        1 for item in jd_items if not (item.requirements or "").strip()
    )
    if missing_requirements:
        missing_ids = [
            item.id for item in jd_items if not (item.requirements or "").strip()
        ]
        id_text = "、".join(missing_ids[:10]) + (" 等" if len(missing_ids) > 10 else "")
        if missing_requirements == jd_sample:
            gaps.append(
                "所有 JD 都缺少 requirements 文本，关键词统计只覆盖标题/描述"
            )
        else:
            gaps.append(
                f"{missing_requirements} 条 JD 缺少 requirements 文本，关键词统计可能偏低"
                f"（已排除出关键词分母：{id_text}）"
            )

    if interview_sample == 0:
        gaps.append("没有面经样本，interview_topics 为空")
    elif interview_sample < 10:
        gaps.append(
            f"面经样本仅 {interview_sample} 条（<10），面经考点置信度低"
        )

    missing_source_jd = sum(
        1 for item in jd_items if not (item.source or item.url)
    )
    if missing_source_jd:
        gaps.append(f"{missing_source_jd} 条 JD 缺少来源链接，可追溯性不足")

    missing_source_interview = sum(
        1 for item in run.interview_items if not (item.source or item.url)
    )
    if missing_source_interview:
        gaps.append(
            f"{missing_source_interview} 条面经缺少来源链接，可追溯性不足"
        )

    unknown_company_jd = sum(
        1 for item in jd_items if not (item.company_id or item.company)
    )
    if unknown_company_jd:
        gaps.append(
            f"{unknown_company_jd} 条 JD 未标注公司，公司覆盖统计可能失真"
        )

    missing_detail = sum(1 for item in jd_items if item.detail_status != "ok")
    if missing_detail:
        gaps.append(f"{missing_detail} 条 JD 详情不完整，关键词统计可能偏低")

    for gap in hard_gate_gaps:
        if gap not in gaps:
            gaps.append(gap)

    for gap in run.gaps:
        text = str(gap).strip()
        if text and text not in gaps:
            gaps.append(f"上游证据缺口：{text}")
    return gaps


def compute_statistics(
    run: EvidenceRun, profile: Any | None = None
) -> dict[str, Any]:
    """从 EvidenceRun 计算 RequirementProfile 的全部确定性字段。"""
    jd_items, excluded_jd, hard_gate_gaps = _apply_hard_gate(run.jd_items, profile)
    tier_by_company = {
        _company_key(item.company_id, item.company): item.tier
        for item in jd_items
    }
    high_frequency, nice_to_have, company_specific = _jd_keyword_analysis(
        jd_items
    )
    interview_topics = _interview_keyword_analysis(
        run.interview_items, tier_by_company
    )
    jd_sample = len(jd_items)
    interview_sample = len(run.interview_items)
    missing_requirements_jd = [
        item.id for item in jd_items if not (item.requirements or "").strip()
    ]
    return {
        "sample_size_jd": jd_sample,
        "sample_size_interview": interview_sample,
        "confidence_jd": _confidence(jd_sample, 15, 30),
        "confidence_interview": _confidence(interview_sample, 10, 20),
        "high_frequency": high_frequency,
        "company_specific": company_specific,
        "interview_topics": interview_topics,
        "hard_requirements": _extract_hard_requirements(jd_items),
        "nice_to_have": nice_to_have,
        "excluded_jd": excluded_jd,
        "missing_requirements_jd": missing_requirements_jd,
        "gaps": _build_gaps(run, jd_items, hard_gate_gaps),
    }


def _resolve_evidence(
    store: Any, profile_name: str, evidence_run_id: str
) -> tuple[dict[str, Any] | None, str, str]:
    if evidence_run_id:
        data = store.load(evidence_run_id)
        if not isinstance(data, dict):
            return None, "", f"EvidenceRun「{evidence_run_id}」不存在"
        meta = data.get("meta")
        if not isinstance(meta, dict) or meta.get("stage") != state_machine.STAGE_EVIDENCE:
            return None, "", f"artifact「{evidence_run_id}」不是 EvidenceRun"
        if str(meta.get("profile_name") or "") != profile_name:
            return None, "", f"EvidenceRun「{evidence_run_id}」不属于当前档案"
        return data, evidence_run_id, ""
    data = store.latest(profile_name, state_machine.STAGE_EVIDENCE)
    if not isinstance(data, dict):
        return None, "", "尚未采集岗位与面经证据，先调用 collect_company_evidence"
    meta = data.get("meta")
    if not isinstance(meta, dict) or meta.get("stage") != state_machine.STAGE_EVIDENCE:
        return None, "", "未找到可用的 EvidenceRun"
    return data, str(meta.get("id") or ""), ""


def build_requirement_profile(
    ctx: StageContext, evidence: EvidenceRun, evidence_run_id: str
) -> RequirementProfile:
    """生成 RequirementProfile 草稿：统计字段由代码计算，interpretation 为空。"""
    profile = load_profile(ctx.profile_name)
    stats = compute_statistics(evidence, profile=profile)
    meta = ArtifactMeta(
        id=ctx.store.new_id("rp"),
        stage=STAGE_ID,
        profile_name=ctx.profile_name,
        created_at=datetime.now().isoformat(),
        inputs={"evidence_run_id": evidence_run_id},
        source_status=[
            dict(item)
            for item in evidence.meta.source_status
            if isinstance(item, dict)
        ],
        validation={
            "method": "deterministic",
            "status": "draft",
            "confidence_jd": stats["confidence_jd"],
            "confidence_interview": stats["confidence_interview"],
        },
    )
    return RequirementProfile(
        meta=meta,
        evidence_run_id=evidence_run_id,
        **stats,
    )


def update_core_state(profile_name: str, requirement_profile_id: str) -> None:
    """写入档案 core_state：需求画像 id、阶段与更新时间。"""
    profile = load_profile(profile_name)
    core_state = dict(profile.core_state or {})
    core_state["requirement_profile_id"] = requirement_profile_id
    core_state["stage"] = STAGE_ID
    core_state["updated_at"] = datetime.now().isoformat()
    profile.core_state = core_state
    profile.touch()
    save_profile(profile, profile_name)


def run(ctx: StageContext, inputs: dict[str, Any]) -> StageResult:
    """执行阶段 8：统计 EvidenceRun 并保存 RequirementProfile 草稿。"""
    evidence_run_id = str(inputs.get("evidence_run_id") or "").strip()
    data, resolved_id, error = _resolve_evidence(
        ctx.store, ctx.profile_name, evidence_run_id
    )
    if data is None:
        return StageResult(
            status="failed",
            code="EVIDENCE_RUN_NOT_FOUND",
            message=error,
            next_stage=STAGE_ID,
        )

    try:
        evidence = EvidenceRun.model_validate(data)
    except Exception as exc:  # noqa: BLE001 —— 损坏数据要变成可读错误
        return StageResult(
            status="failed",
            code="EVIDENCE_RUN_CORRUPT",
            message=f"EvidenceRun 数据损坏，无法分析：{exc}",
            next_stage=STAGE_ID,
        )

    artifact = build_requirement_profile(ctx, evidence, resolved_id)
    issues = validate(artifact)
    if issues:
        return StageResult(
            status="failed",
            code="REQUIREMENT_VALIDATION_FAILED",
            message="需求画像校验失败：" + "；".join(issues),
            next_stage=STAGE_ID,
            details={"issues": issues},
        )

    ctx.store.save(artifact)
    update_core_state(ctx.profile_name, artifact.meta.id)
    summary = (
        f"需求画像草稿已生成：JD {artifact.sample_size_jd} 条"
        f"（{artifact.confidence_jd}），面经 {artifact.sample_size_interview} 条"
        f"（{artifact.confidence_interview}）；高频共性 "
        f"{len(artifact.high_frequency)} 项，公司差异化 "
        f"{len(artifact.company_specific)} 项。"
    )
    # 只落草稿；下一工具是同阶段的 save_requirement_profile，不是阶段 9。
    return StageResult(
        status="ok",
        artifact_id=artifact.meta.id,
        message=f"{summary}\n\n{build_analysis_prompt(artifact)}",
        next_stage=STAGE_ID,
        warnings=list(artifact.gaps),
    )


def known_evidence_ids(artifact: RequirementProfile) -> set[str]:
    """RequirementProfile 中真实存在的 evidence id 集合（统计与硬门槛共用）。"""
    ids: set[str] = set()
    for items in (
        artifact.high_frequency,
        artifact.nice_to_have,
        artifact.company_specific,
        artifact.interview_topics,
    ):
        for item in items:
            ids.update(clean_evidence_ids(item.evidence_ids))
    for hard in artifact.hard_requirements:
        if hard.evidence_id.strip():
            ids.add(hard.evidence_id.strip())
    return ids


def _flatten_text(value: Any) -> str:
    if isinstance(value, (str, int, float)):
        return str(value)
    if isinstance(value, (list, tuple, set)):
        return " ".join(_flatten_text(item) for item in value)
    if isinstance(value, dict):
        return " ".join(_flatten_text(item) for item in value.values())
    return ""


def _interpretation_problems(artifact: RequirementProfile) -> list[str]:
    """interpretation 中一旦引用 JD/IV id，就必须是 RequirementProfile 里真实存在的。"""
    text = " ".join(
        _flatten_text(value) for value in artifact.interpretation.values()
    )
    tokens = sorted({token.upper() for token in _EVIDENCE_TOKEN_PATTERN.findall(text)})
    if not tokens:
        return []
    known = known_evidence_ids(artifact)
    unknown = sorted(token for token in tokens if token not in known)
    if not unknown:
        return []
    return [
        "interpretation 引用了不存在的 evidence_ids："
        f"{unknown}（可用：{sorted(known) or '无'}）"
    ]


def _validate_item(item: RequirementItem, list_name: str) -> list[str]:
    issues: list[str] = []
    prefix = f"{list_name}.{item.term}"
    if item.jd_count < 0:
        issues.append(f"{prefix}: jd_count 不能为负")
    if not 0.0 <= item.jd_frequency <= 1.0:
        issues.append(f"{prefix}: jd_frequency 必须在 0-1 之间")
    if item.company_count < 0:
        issues.append(f"{prefix}: company_count 不能为负")
    if not 0.0 <= item.company_frequency <= 1.0:
        issues.append(f"{prefix}: company_frequency 必须在 0-1 之间")
    if item.company_count > item.jd_count:
        issues.append(f"{prefix}: company_count 不能大于 jd_count")
    if len(item.companies) != item.company_count:
        issues.append(f"{prefix}: companies 数量与 company_count 不一致")
    if len(item.evidence_ids) != item.jd_count:
        issues.append(f"{prefix}: evidence_ids 数量与 jd_count 不一致")
    for label, value in (("ci_low", item.ci_low), ("ci_high", item.ci_high)):
        if value is not None and not 0.0 <= value <= 1.0:
            issues.append(f"{prefix}: {label} 必须在 0-1 之间")
    if item.ci_low is not None and item.ci_high is not None:
        if item.ci_low > item.ci_high:
            issues.append(f"{prefix}: ci_low 不能大于 ci_high")
        elif not (
            item.ci_low - _TOLERANCE
            <= item.jd_frequency
            <= item.ci_high + _TOLERANCE
        ):
            issues.append(f"{prefix}: jd_frequency 未落在置信区间内")
    return issues


def _validate_frequency(
    item: RequirementItem, list_name: str, sample_size: int
) -> list[str]:
    expected = round(item.jd_count / sample_size, 4) if sample_size else 0.0
    if abs(item.jd_frequency - expected) > _CI_TOLERANCE:
        return [
            f"{list_name}.{item.term}: jd_frequency 应为 {expected}，"
            f"实际 {item.jd_frequency}（数字必须由代码计算）"
        ]
    low, high = wilson_interval(item.jd_count, sample_size)
    issues: list[str] = []
    if (
        low is not None
        and item.ci_low is not None
        and abs(item.ci_low - low) > _CI_TOLERANCE
    ):
        issues.append(f"{list_name}.{item.term}: ci_low 与 Wilson 公式不一致")
    if (
        high is not None
        and item.ci_high is not None
        and abs(item.ci_high - high) > _CI_TOLERANCE
    ):
        issues.append(f"{list_name}.{item.term}: ci_high 与 Wilson 公式不一致")
    return issues


def validate(artifact: BaseModel) -> list[str]:
    """校验 artifact 的确定性字段与 interpretation 边界。"""
    if not isinstance(artifact, RequirementProfile):
        return ["artifact 类型必须是 RequirementProfile"]
    issues: list[str] = []

    extra_keys = sorted(set(artifact.interpretation) - set(INTERPRETATION_KEYS))
    if extra_keys:
        issues.append(
            f"interpretation 只允许 {list(INTERPRETATION_KEYS)}，拒绝字段：{extra_keys}"
        )
    issues.extend(_interpretation_problems(artifact))

    # 关键词分析排除了缺 requirements 文本的 JD，校验必须用同一个分母。
    keyword_sample = artifact.sample_size_jd - len(artifact.missing_requirements_jd)
    if keyword_sample <= 0:
        keyword_sample = artifact.sample_size_jd

    for list_name, items in (
        ("high_frequency", artifact.high_frequency),
        ("nice_to_have", artifact.nice_to_have),
        ("company_specific", artifact.company_specific),
    ):
        for item in items:
            issues.extend(_validate_item(item, list_name))
            issues.extend(_validate_frequency(item, list_name, keyword_sample))

    for item in artifact.interview_topics:
        issues.extend(_validate_item(item, "interview_topics"))
        issues.extend(
            _validate_frequency(item, "interview_topics", artifact.sample_size_interview)
        )

    for item in artifact.high_frequency:
        if item.jd_frequency < 0.5 or item.company_count < 2:
            issues.append(
                f"high_frequency.{item.term}: 不满足 jd_frequency>=0.5 且 company_count>=2"
            )

    for item in artifact.company_specific:
        if item.company_count != 1:
            issues.append(
                f"company_specific.{item.term}: 每项只应包含一家公司"
            )
        if item.jd_count < 2:
            issues.append(
                f"company_specific.{item.term}: 单家公司命中数必须 >=2"
            )

    for item in artifact.hard_requirements:
        if not item.evidence_id:
            issues.append("hard_requirements: evidence_id 不能为空")

    if artifact.sample_size_jd < 0 or artifact.sample_size_interview < 0:
        issues.append("sample_size 不能为负")
    return issues


def summary_dict(artifact: RequirementProfile) -> dict[str, Any]:
    """工具层摘要：只读 artifact，不重新计算。"""
    return {
        "requirement_profile_id": artifact.meta.id,
        "evidence_run_id": artifact.evidence_run_id,
        "sample_size": {
            "jd": artifact.sample_size_jd,
            "interview": artifact.sample_size_interview,
        },
        "confidence": {
            "jd": artifact.confidence_jd,
            "interview": artifact.confidence_interview,
        },
        "high_frequency": [item.model_dump() for item in artifact.high_frequency],
        "nice_to_have": [item.model_dump() for item in artifact.nice_to_have],
        "company_specific": [
            item.model_dump() for item in artifact.company_specific
        ],
        "interview_topics": [
            item.model_dump() for item in artifact.interview_topics
        ],
        "hard_requirements": [
            item.model_dump() for item in artifact.hard_requirements
        ],
        "excluded_jd": list(artifact.excluded_jd),
        "missing_requirements_jd": list(artifact.missing_requirements_jd),
        "gaps": list(artifact.gaps),
        "interpretation": artifact.interpretation,
    }


def _prompt_items(items: list[RequirementItem], limit: int = 8) -> str:
    bits = []
    for item in items[:limit]:
        evidence = ",".join(item.evidence_ids[:5])
        bits.append(
            f"{item.term}（{item.jd_count} 条 / {item.company_count} 家"
            f"{'，evidence: ' + evidence if evidence else ''}）"
        )
    text = "；".join(bits)
    if len(items) > limit:
        text += f"；…共 {len(items)} 项，此处展示前 {limit} 项"
    return text


def sample_warnings(artifact: RequirementProfile) -> list[str]:
    """样本不足的强提示（返回体顶部展示，不改变统计结果）。"""
    notes: list[str] = []
    if artifact.sample_size_jd < 15:
        notes.append(
            f"JD 有效样本仅 {artifact.sample_size_jd} 条（<15），置信度 {artifact.confidence_jd}；"
            "建议先补采目标企业 JD 再据此定稿。"
        )
    if artifact.missing_requirements_jd:
        notes.append(
            f"{len(artifact.missing_requirements_jd)} 条 JD 缺 requirements 文本"
            f"（{', '.join(artifact.missing_requirements_jd[:10])}），已排除出关键词分母，"
            "关键词统计可能偏低。"
        )
    if artifact.sample_size_interview < 10:
        notes.append(
            f"面经有效样本仅 {artifact.sample_size_interview} 条（<10），"
            f"置信度 {artifact.confidence_interview}；面试考点只作方向参考。"
        )
    return notes


def build_analysis_prompt(artifact: RequirementProfile) -> str:
    """给 LLM 的受约束解读提示；数字与 evidence_ids 已由代码固定。"""
    lines = [
        "你已完成企业需求分析的确定性统计。数字、公司覆盖、置信区间均由代码计算，",
        "你只能填写 interpretation（定性解读），不得修改任何数字、列表或 evidence_ids。",
        f"- requirement_profile_id：{artifact.meta.id}",
        f"- 样本：{artifact.sample_size_jd} 条 JD，"
        f"{artifact.sample_size_interview} 条面经",
        f"- 置信度：JD {artifact.confidence_jd}；面经 {artifact.confidence_interview}",
    ]
    if artifact.high_frequency:
        lines.append(
            "- 高频共性要求：" + _prompt_items(artifact.high_frequency)
        )
    if artifact.nice_to_have:
        lines.append("- 加分项/次级共性：" + _prompt_items(artifact.nice_to_have))
    if artifact.company_specific:
        lines.append(
            "- 公司差异化要求：" + _prompt_items(artifact.company_specific)
        )
    if artifact.interview_topics:
        lines.append(
            "- 面经高频考点：" + _prompt_items(artifact.interview_topics)
        )
    if artifact.hard_requirements:
        total_hard = len(artifact.hard_requirements)
        shown = artifact.hard_requirements[:8]
        hard_bits = []
        for hard in shown:
            detail = "、".join(
                value for value in (hard.education, hard.experience) if value
            )
            hard_bits.append(f"{hard.evidence_id}: {detail or '未识别'}")
        suffix = (
            f"（共 {total_hard} 条，以下展示前 {len(shown)} 条，完整清单见 hard_requirements 字段）"
            if total_hard > len(shown)
            else f"（共 {total_hard} 条）"
        )
        lines.append(
            f"- 单 JD 硬门槛（逐条，不聚合）{suffix}：" + "；".join(hard_bits)
        )
    if artifact.gaps:
        lines.append("- 数据缺口：" + "；".join(artifact.gaps))

    lines.extend(
        [
            "",
            "输出要求：只返回一个 JSON 对象，结构如下：",
            "{",
            f'  "requirement_profile_id": "{artifact.meta.id}",',
            '  "interpretation": {',
            '    "summary": "总体解读",',
            '    "priorities": ["优先级说明"],',
            '    "company_notes": ["公司差异说明"],',
            '    "risks": ["风险与不确定项"],',
            '    "notes": ["其他说明"]',
            "  }",
            "}",
            "",
            "硬性约束：",
            "1. interpretation 只允许 summary / priorities / company_notes / risks / notes 五个键；",
            "   禁止写入 high_frequency、company_specific、interview_topics、hard_requirements、",
            "   nice_to_have、gaps、sample_size、confidence 等数字或列表字段。",
            "2. interpretation 可以不引用 evidence_ids；一旦引用，必须使用上面统计里真实出现过的 id"
            "（如 JD001、IV002）。引用不存在的 id 会被拒绝落库，不要编造。",
            "3. 使用「高频共性要求 / 单 JD 硬门槛 / 面经高频考点 / 公司差异化要求 / 加分项」口径，",
            "   不要使用「必备项」这类绝对说法。",
            "4. 置信度为 low 时必须明确说明样本不足，不下全局结论。",
        ]
    )
    return "\n".join(lines)


__all__ = [
    "INTERPRETATION_KEYS",
    "PRODUCES",
    "REQUIRES",
    "STAGE_ID",
    "build_analysis_prompt",
    "build_requirement_profile",
    "compute_statistics",
    "known_evidence_ids",
    "run",
    "sample_warnings",
    "summary_dict",
    "update_core_state",
    "validate",
    "wilson_interval",
]
