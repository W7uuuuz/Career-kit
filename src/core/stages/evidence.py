"""阶段 7：岗位与面经采集。

只负责采集事实：抓取、去重、城市硬筛、详情补抓、来源状态与样本置信度。
LLM 不参与；单源失败只进 source_status 与 gaps，不拖垮整批。
产物是 EvidenceRun artifact，报告由 `core.reporting.evidence_report` 渲染。
"""

from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel

from ...case_search import collect_cases
from ...scrapers import catalog, loader
from ...scrapers.loader import get_job_detail, search_company_jobs
from ...tools.profile import load_profile, save_profile
from ..artifacts.models import (
    ArtifactMeta,
    CompanyEntry,
    CompanyPool,
    EvidenceRun,
    InterviewEvidence,
    JDEvidence,
    TargetSpec,
)
from ..orchestrator import state_machine
from ..reporting import evidence_report
from .base import StageContext, StageResult

STAGE_ID = state_machine.STAGE_EVIDENCE
REQUIRES = ("company_pool",)
PRODUCES = "evidence_run"

CONCURRENCY = 4
SOURCE_TIMEOUT = float(os.environ.get("CAREER_KIT_EVIDENCE_TIMEOUT", "20") or 20)
SOURCE_RETRY = 1
TOTAL_BUDGET = 120.0
RESEARCH_TTL_DAYS = 7
MAX_DETAIL_FETCH = 20
DEFAULT_PER_COMPANY_LIMIT = 5
DEFAULT_MAX_COMPANIES = 15
DEFAULT_MAX_JD = 50
DEFAULT_MAX_INTERVIEWS = 30
BOSS_SOURCE = "boss"

_REMOTE_HINTS = ("远程", "全国", "不限", "remote", "anywhere")
_CONFIDENCE_LEVELS = ("low", "medium", "high")

# 采集层岗位相关性：目标岗位关键词，以及岗位族扩展词。
# 只做字面命中，不做语义推断；宁可少收，也不让跑偏岗位污染统计。
_GENERIC_ROLE_TERMS = frozenset(
    {"开发", "工程师", "研发", "经理", "专员", "主管", "总监", "助理", "实习", "岗位"}
)
_AI_SIGNALS = (
    "ai", "agent", "llm", "大模型", "模型", "算法", "机器学习", "深度学习",
    "nlp", "rag", "langchain", "langgraph", "智能",
)
_AI_FAMILY_TERMS = (
    "ai", "agent", "llm", "大模型", "模型", "算法", "机器学习", "深度学习",
    "nlp", "rag", "langchain", "langgraph", "prompt", "智能",
)
_ENGINEERING_SIGNALS = ("开发", "工程师", "研发", "后端", "服务端", "backend", "engineer", "developer")
_ENGINEERING_TERMS = (
    "开发", "工程师", "研发", "后端", "服务端", "python", "java", "go", "golang",
    "微服务", "分布式", "高并发",
)
_ROLE_TOKEN_SPLIT_RE = re.compile(r"[\s,，、;；/|()（）\-]+")
_ASCII_TOKEN_RE = re.compile(r"[a-z][a-z0-9+#.\-]*")
_CJK_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]{2,}")



def run(ctx: StageContext, inputs: dict[str, Any]) -> StageResult:
    """同步入口（Stage 协议）；异步内部实现见 `run_async`。"""
    return asyncio.run(run_async(ctx, inputs))


async def run_async(ctx: StageContext, inputs: dict[str, Any]) -> StageResult:
    """执行阶段 7：抓取目标企业的 JD 与面经并保存 EvidenceRun。"""
    store = ctx.store
    requested_pool_id = str(inputs.get("company_pool_id") or "").strip()
    pool_data, pool_id, error = _resolve_pool(store, ctx.profile_name, requested_pool_id)
    if pool_data is None:
        return StageResult(status="failed", message=error, next_stage=STAGE_ID)
    try:
        pool = CompanyPool.model_validate(pool_data)
    except Exception as exc:  # noqa: BLE001 - 损坏数据要变成可读错误
        return StageResult(
            status="failed",
            message=f"CompanyPool 数据损坏，无法采集：{exc}",
            next_stage=STAGE_ID,
        )
    if not _pool_confirmed(pool):
        return StageResult(
            status="failed",
            message="CompanyPool 尚未确认，先调用 select_target_companies 并确认名单。",
            next_stage=state_machine.STAGE_COMPANY_POOL,
        )

    target = pool.target_spec.model_copy(deep=True)
    target_keyword = _target_search_keyword(target)
    per_company_limit = _as_int(inputs.get("per_company_limit"), DEFAULT_PER_COMPANY_LIMIT, 1)
    max_companies = _as_int(inputs.get("max_companies"), DEFAULT_MAX_COMPANIES, 1)
    max_jd = _as_int(inputs.get("max_jd"), DEFAULT_MAX_JD, 0)
    max_interviews = _as_int(inputs.get("max_interviews"), DEFAULT_MAX_INTERVIEWS, 0)
    reuse_research = not _as_bool(inputs.get("refresh"))
    include_boss = _as_bool(inputs.get("include_boss"))
    boss_confirmed = _as_bool(inputs.get("boss_confirmed"))

    profile = load_profile(ctx.profile_name)
    education = _education_of(profile)
    selected = [entry for entry in pool.companies if entry.scrapable and entry.status != "excluded"]
    selected = selected[:max_companies]
    if not selected:
        return StageResult(
            status="insufficient_data",
            message="目标企业池中没有可自动抓取的企业，无法采集证据。",
            next_stage=STAGE_ID,
            warnings=["请调整企业池：至少确认一家已接入 scraper 的企业。"],
        )

    loop = asyncio.get_running_loop()
    deadline = loop.time() + TOTAL_BUDGET
    semaphore = asyncio.Semaphore(CONCURRENCY)

    jd_tasks = [
        _search_company_jobs(
            entry, slug, target_keyword, target.city, per_company_limit, deadline, semaphore
        )
        for entry in selected
        for slug in _entry_scrapers(entry)
    ]
    if include_boss and max_jd != 0:
        jd_tasks.append(
            _search_boss_jobs(
                target, target_keyword, _boss_limit(max_jd, per_company_limit),
                deadline, semaphore,
            )
        )
    jd_results = await asyncio.gather(*jd_tasks)
    source_status: list[dict[str, Any]] = [
        {
            "source": result["source"],
            "scope": "jd",
            "status": result["status"],
            "count": result["count"],
            "error": result["error"],
            "elapsed": round(result["elapsed"], 3),
        }
        for result in jd_results
    ]
    interview_status, raw_cases = await _collect_interviews(
        target, target_keyword, education, max_interviews, deadline, semaphore
    )
    source_status.extend(interview_status)

    fetched_company_ids = {
        result["entry"].id
        for result in jd_results
        if result.get("entry") is not None and result["status"] != "failed"
    }
    counts: dict[str, int] = {
        "companies_requested": len(selected),
        "companies_fetched": len(fetched_company_ids),
        "raw_jobs": sum(int(result["count"]) for result in jd_results),
        "kept_jobs": 0,
        "fresh_jobs": 0,
        "dropped_city": 0,
        "dropped_no_detail": 0,
        "interviews": 0,
        "reused_jd": 0,
        "reused_interviews": 0,
        "reused_jd_outside_pool": 0,
        "reused_interviews_outside_pool": 0,
        "reused_outside_pool": 0,
        "dropped_irrelevant": 0,
        "unknown_city": 0,
        "boss_jobs": 0,
        "list_only": 0,
        "list_only_kept": 0,
        "list_only_dropped_city": 0,
    }

    fresh_jd, counts = await _enrich_jobs(jd_results, target.city, deadline, semaphore, counts)
    fresh_jd, irrelevant_samples = _filter_relevant_jobs(fresh_jd, target_keyword, counts)
    fresh_jd = _dedupe_jobs(fresh_jd)
    fresh_jd = _truncate_per_company(fresh_jd, per_company_limit)

    reused_jd: list[JDEvidence] = []
    if reuse_research:
        reused_jd, counts = _reuse_jobs(profile, pool, target.city, counts)

    final_jd = _merge_jobs(fresh_jd, reused_jd, max_jd)
    # list-only 计数必须在去重 / 按企业截断 / 总量截断之后按终态重算，
    # 否则截断前计数会与 jd_items 不一致，导致整批证据池校验失败。
    _recompute_list_only_counts(counts, final_jd)

    fresh_interviews = _to_interviews(raw_cases)
    fresh_interviews = _dedupe_interviews(fresh_interviews)
    reused_interviews: list[InterviewEvidence] = []
    if reuse_research:
        reused_interviews = _reuse_interviews(profile, pool)
    final_interviews = _merge_interviews(fresh_interviews, reused_interviews, max_interviews)

    _assign_ids(final_jd, "JD")
    _assign_ids(final_interviews, "IV")

    counts["kept_jobs"] = len(final_jd)
    counts["interviews"] = len(final_interviews)
    counts["reused_jd"] = sum(1 for item in final_jd if item.reused)
    counts["fresh_jobs"] = len(final_jd) - counts["reused_jd"]
    counts["reused_interviews"] = sum(1 for item in final_interviews if item.reused)
    counts["reused_jd_outside_pool"] = sum(
        1 for item in final_jd if item.reused and not item.reused_in_pool
    )
    counts["reused_interviews_outside_pool"] = sum(
        1 for item in final_interviews if item.reused and not item.reused_in_pool
    )
    counts["reused_outside_pool"] = (
        counts["reused_jd_outside_pool"] + counts["reused_interviews_outside_pool"]
    )
    counts["boss_jobs"] = sum(1 for item in final_jd if item.source == BOSS_SOURCE)
    confidence = {
        "jd": _confidence(len(final_jd), low=15, medium=30),
        "interview": _confidence(len(final_interviews), low=10, medium=20),
    }
    gaps = _build_gaps(
        pool,
        source_status,
        counts,
        confidence,
        target.city,
        jd_items=final_jd,
        interview_items=final_interviews,
        irrelevant_samples=irrelevant_samples,
    )

    meta = ArtifactMeta(
        id=store.new_id("ev_"),
        stage=STAGE_ID,
        profile_name=ctx.profile_name,
        created_at=datetime.now().isoformat(),
        inputs={
            "company_pool_id": pool_id,
            "role": target.role,
            "city": target.city,
            "max_companies": str(max_companies),
            "per_company_limit": str(per_company_limit),
            "max_jd": str(max_jd),
            "max_interviews": str(max_interviews),
            "refresh": "true" if not reuse_research else "false",
            "include_boss": "true" if include_boss else "false",
            "boss_confirmed": "true" if boss_confirmed else "false",
        },
        source_status=source_status,
        validation={
            "confirmed": True,
            "companies": len(selected),
            "jd_items": len(final_jd),
            "interview_items": len(final_interviews),
        },
    )
    evidence = EvidenceRun(
        meta=meta,
        target_spec=target,
        company_pool_id=pool_id,
        jd_items=final_jd,
        interview_items=final_interviews,
        counts=counts,
        confidence=confidence,
        gaps=gaps,
    )

    if not final_jd and not final_interviews:
        return StageResult(
            status="insufficient_data",
            message="本次采集没有得到任何可用 JD 或面经，未保存空证据池。",
            next_stage=STAGE_ID,
            warnings=gaps,
        )

    issues = validate(evidence)
    if issues:
        return StageResult(
            status="failed",
            message="证据池校验失败：" + "；".join(issues),
            next_stage=STAGE_ID,
            warnings=gaps,
        )

    evidence.report_paths = evidence_report.save_report(evidence, profile_name=ctx.profile_name)
    store.save(evidence)
    _update_core_state(ctx.profile_name, evidence.meta.id)

    message = (
        f"已采集 JD：新抓 {counts['fresh_jobs']} 条 + 复用 {counts['reused_jd']} 条 "
        f"= 保留 {counts['kept_jobs']} 条（置信度 {confidence['jd']}）；"
        f"面经 {counts['interviews']} 条（置信度 {confidence['interview']}），"
        f"其中复用 {counts['reused_interviews']} 条。"
    )
    return StageResult(
        status="ok",
        artifact_id=evidence.meta.id,
        message=message,
        next_stage=state_machine.STAGE_REQUIREMENT,
        warnings=gaps,
    )


def validate(artifact: BaseModel) -> list[str]:
    """校验 EvidenceRun：阶段一致、id 唯一、计数自洽。"""
    if not isinstance(artifact, EvidenceRun):
        return ["artifact 必须是 EvidenceRun"]

    issues: list[str] = []
    if artifact.meta.stage != STAGE_ID:
        issues.append(f"meta.stage 应为 {STAGE_ID}，实际为 {artifact.meta.stage}")
    if not artifact.company_pool_id.strip():
        issues.append("company_pool_id 不能为空")
    if not artifact.jd_items and not artifact.interview_items:
        issues.append("JD 与面经同时为空，不能保存证据池")

    seen: set[str] = set()
    for item in artifact.jd_items:
        if not item.id.strip():
            issues.append("存在空 id 的 JD")
        elif item.id in seen:
            issues.append(f"JD id 重复：{item.id}")
        seen.add(item.id)
        if not item.title.strip():
            issues.append(f"JD {item.id} 缺少 title")
        if not item.company_id.strip() and not item.company.strip():
            issues.append(f"JD {item.id} 缺少公司信息")

    seen.clear()
    for item in artifact.interview_items:
        if not item.id.strip():
            issues.append("存在空 id 的面经")
        elif item.id in seen:
            issues.append(f"面经 id 重复：{item.id}")
        seen.add(item.id)
        if not item.title.strip():
            issues.append(f"面经 {item.id} 缺少 title")

    for key in ("jd", "interview"):
        if artifact.confidence.get(key) not in _CONFIDENCE_LEVELS:
            issues.append(f"confidence.{key} 必须是 {_CONFIDENCE_LEVELS} 之一")

    counts = artifact.counts
    if counts.get("kept_jobs", len(artifact.jd_items)) != len(artifact.jd_items):
        issues.append("counts.kept_jobs 与 jd_items 数量不一致")
    if counts.get("interviews", len(artifact.interview_items)) != len(artifact.interview_items):
        issues.append("counts.interviews 与 interview_items 数量不一致")
    if counts.get("reused_jd", 0) != sum(1 for item in artifact.jd_items if item.reused):
        issues.append("counts.reused_jd 与 reused 标记数量不一致")
    if counts.get("reused_interviews", 0) != sum(
        1 for item in artifact.interview_items if item.reused
    ):
        issues.append("counts.reused_interviews 与 reused 标记数量不一致")
    actual_list_only = sum(
        1 for item in artifact.jd_items if item.detail_status == "list_only"
    )
    kept_list_only = counts.get("list_only_kept", counts.get("list_only", 0))
    if kept_list_only != actual_list_only:
        issues.append("counts.list_only_kept 与 list_only 标记数量不一致")
    if "list_only" in counts and counts.get("list_only") != (
        actual_list_only + int(counts.get("list_only_dropped_city") or 0)
    ):
        issues.append("counts.list_only 与 list_only_kept + list_only_dropped_city 不一致")
    return issues


def _resolve_pool(
    store: Any, profile_name: str, pool_id: str
) -> tuple[dict[str, Any] | None, str, str]:
    if pool_id:
        data = store.load(pool_id)
        if not isinstance(data, dict):
            return None, pool_id, f"CompanyPool「{pool_id}」不存在"
        if not _is_pool_of_profile(data, profile_name):
            return None, pool_id, f"CompanyPool「{pool_id}」不属于当前档案或类型不符"
        return data, pool_id, ""

    core_id = _core_state_pool_id(profile_name)
    if core_id:
        data = store.load(core_id)
        if _is_pool_of_profile(data, profile_name):
            return data, core_id, ""

    data = store.latest(profile_name, state_machine.STAGE_COMPANY_POOL)
    if not _is_pool_of_profile(data, profile_name):
        return None, "", "尚未生成目标企业池，先调用 select_target_companies"
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    return data, str(meta.get("id") or ""), ""


def _core_state_pool_id(profile_name: str) -> str:
    try:
        profile = load_profile(profile_name)
    except Exception:  # noqa: BLE001 - 档案读取失败时回退 latest
        return ""
    core_state = getattr(profile, "core_state", None)
    if not isinstance(core_state, dict):
        return ""
    return str(core_state.get("company_pool_id") or "").strip()


def _is_pool_of_profile(data: Any, profile_name: str) -> bool:
    if not isinstance(data, dict):
        return False
    meta = data.get("meta")
    if not isinstance(meta, dict):
        return False
    return (
        meta.get("stage") == state_machine.STAGE_COMPANY_POOL
        and str(meta.get("profile_name") or "") == profile_name
    )


def _pool_confirmed(pool: CompanyPool) -> bool:
    if pool.meta.validation.get("confirmed") is True:
        return True
    return any(entry.status == "confirmed" for entry in pool.companies)


def _education_of(profile: Any) -> str:
    for section in (getattr(profile, "who", {}) or {}, getattr(profile, "want", {}) or {}):
        if not isinstance(section, dict):
            continue
        value = section.get("education") or section.get("education_tag")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _as_int(value: Any, default: int, minimum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(number, minimum)


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "是"}
    return bool(value)


def _entry_scrapers(entry: CompanyEntry) -> list[str]:
    scrapers = [str(item).strip() for item in entry.scrapers if str(item).strip()]
    return scrapers or [entry.id]


def _scraper_params(slug: str) -> dict[str, Any]:
    try:
        return loader.scraper_params(slug)
    except Exception:  # noqa: BLE001 - 参数发现失败时只传 limit
        return {}


def _search_params(slug: str, role: str, city: str, limit: int) -> dict[str, Any]:
    supported = _scraper_params(slug)
    params: dict[str, Any] = {"limit": limit}
    if not supported:
        # 未声明参数能力的源不硬塞 keyword/city，避免 loader 判定未知参数。
        return params
    if role and "keyword" in supported:
        params["keyword"] = role
    if city and "city" in supported:
        params["city"] = city
    return params


def _target_search_keyword(target: TargetSpec) -> str:
    """目标岗位关键词的唯一来源：TargetSpec.role 优先，空时回退 direction。"""
    return (target.role or "").strip() or (target.direction or "").strip()


def _keyword_terms(keyword: str) -> tuple[list[str], list[str]]:
    """把目标关键词拆成核心词与岗位族扩展词（只做字面匹配）。"""
    text = str(keyword or "").strip().lower()
    if not text:
        return [], []
    core: list[str] = [part for part in _ROLE_TOKEN_SPLIT_RE.split(text) if part]
    if not core:
        core = [text]
    core.extend(match.group(0) for match in _ASCII_TOKEN_RE.finditer(text))
    core.extend(match.group(0) for match in _CJK_TOKEN_RE.finditer(text))
    core = _dedupe_terms(core)

    family: list[str] = []
    if any(signal in text for signal in _AI_SIGNALS):
        family.extend(_AI_FAMILY_TERMS)
    if any(signal in text for signal in _ENGINEERING_SIGNALS):
        family.extend(_ENGINEERING_TERMS)
    return core, _dedupe_terms(family)


def _dedupe_terms(terms: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for term in terms:
        value = str(term or "").strip().lower()
        if len(value) < 2 or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _term_in(term: str, text: str) -> bool:
    if term.isascii():
        pattern = rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])"
        return re.search(pattern, text) is not None
    return term in text


def _job_is_relevant(title: str, text: str, keyword: str) -> bool:
    """按标题/正文与目标岗位关键词打分：宁少不脏。"""
    phrase = " ".join(str(keyword or "").lower().split())
    if not phrase:
        return True
    haystack_title = str(title or "").lower()
    haystack_text = str(text or "").lower()
    if phrase in haystack_title or phrase.replace(" ", "") in haystack_title.replace(" ", ""):
        return True

    core, family = _keyword_terms(phrase)
    terms = _dedupe_terms(core + family)
    matched_core = {term for term in core if _term_in(term, haystack_title) or _term_in(term, haystack_text)}
    matched_all = {
        term
        for term in terms
        if _term_in(term, haystack_title) or _term_in(term, haystack_text)
    }
    if len(matched_all) >= 2:
        return True
    # 中文核心词（如「市场」）单独命中即可；通用词（如「开发」）不算。
    return any(
        not term.isascii()
        and term not in _GENERIC_ROLE_TERMS
        and _term_in(term, haystack_title)
        for term in matched_core
    )


def _filter_relevant_jobs(
    items: list[JDEvidence], keyword: str, counts: dict[str, int]
) -> tuple[list[JDEvidence], list[str]]:
    if not keyword:
        return items, []
    kept: list[JDEvidence] = []
    dropped: list[str] = []
    for item in items:
        text = " ".join((item.summary, item.description, item.requirements))
        if _job_is_relevant(item.title, text, keyword):
            kept.append(item)
        else:
            counts["dropped_irrelevant"] += 1
            dropped.append(item.title)
    return kept, dropped


def _boss_limit(max_jd: int, per_company_limit: int) -> int:
    """BOSS 抓取上限：受最终 JD 预算约束，未给预算时退化为单企业配额。"""
    return max_jd if max_jd > 0 else per_company_limit


async def _search_boss_jobs(
    target: TargetSpec,
    keyword: str,
    limit: int,
    deadline: float,
    semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    """抓取 BOSS 直聘作为跨公司补充源；不占企业池名额。"""
    if not keyword:
        return _source_result(
            None, BOSS_SOURCE, "failed", 0, "目标岗位为空，无法搜索 BOSS", 0.0
        )
    params: dict[str, Any] = {"limit": limit, "keyword": keyword}
    if target.city:
        params["city"] = target.city

    loop = asyncio.get_running_loop()
    request_started = loop.time()
    async with semaphore:
        started = loop.time()
        remaining = deadline - started
        if remaining <= 0:
            return _source_result(
                None,
                BOSS_SOURCE,
                "failed",
                0,
                "总预算耗尽，未执行 BOSS 抓取",
                loop.time() - request_started,
            )
        timeout = min(SOURCE_TIMEOUT, remaining)
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(search_company_jobs, BOSS_SOURCE, **params), timeout=timeout
            )
        except TimeoutError:
            return _source_result(
                None, BOSS_SOURCE, "failed", 0, f"抓取超时（{timeout:.0f} 秒）", timeout
            )
        except Exception as exc:  # noqa: BLE001 - 单源异常不拖垮整批
            return _source_result(
                None,
                BOSS_SOURCE,
                "failed",
                0,
                f"{type(exc).__name__}: {exc}",
                loop.time() - started,
            )
    elapsed = loop.time() - started
    if not isinstance(response, dict):
        return _source_result(None, BOSS_SOURCE, "failed", 0, "抓取返回格式异常", elapsed)

    error = str(response.get("error") or "").strip()
    if error:
        return _source_result(None, BOSS_SOURCE, "failed", 0, error, elapsed)

    rows = [
        row
        for row in response.get("results") or []
        if isinstance(row, dict) and not row.get("error")
    ]
    warnings = [str(item) for item in response.get("warnings") or [] if str(item).strip()]
    status = "ok" if rows else "empty"
    if not rows and warnings:
        status = "failed"
    return _source_result(
        None, BOSS_SOURCE, status, len(rows), "；".join(warnings), elapsed, rows=rows
    )


async def _search_company_jobs(
    entry: CompanyEntry,
    slug: str,
    role: str,
    city: str,
    limit: int,
    deadline: float,
    semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    params = _search_params(slug, role, city, limit)
    loop = asyncio.get_running_loop()
    request_started = loop.time()
    async with semaphore:
        started = loop.time()
        response: Any = None
        for attempt in range(SOURCE_RETRY + 1):
            remaining = deadline - loop.time()
            if remaining <= 0:
                return _source_result(
                    entry, slug, "failed", 0, "总预算耗尽，未执行抓取",
                    loop.time() - request_started,
                )
            timeout = min(SOURCE_TIMEOUT, remaining)
            try:
                response = await asyncio.wait_for(
                    asyncio.to_thread(search_company_jobs, slug, **params), timeout=timeout
                )
                break
            except TimeoutError:
                if attempt >= SOURCE_RETRY or deadline - loop.time() <= 1:
                    suffix = "，已重试 1 次" if attempt else ""
                    return _source_result(
                        entry, slug, "failed", 0,
                        f"抓取超时（{timeout:.0f} 秒）{suffix}",
                        loop.time() - started,
                    )
            except Exception as exc:  # noqa: BLE001 - 单源异常不拖垮整批
                return _source_result(
                    entry, slug, "failed", 0, f"{type(exc).__name__}: {exc}",
                    loop.time() - started,
                )
    elapsed = loop.time() - started
    if not isinstance(response, dict):
        return _source_result(entry, slug, "failed", 0, "抓取返回格式异常", elapsed)

    error = str(response.get("error") or "").strip()
    if error:
        return _source_result(entry, slug, "failed", 0, error, elapsed)

    rows = [
        row
        for row in response.get("results") or []
        if isinstance(row, dict) and not row.get("error")
    ]
    warnings = [str(item) for item in response.get("warnings") or [] if str(item).strip()]
    status = "ok" if rows else "empty"
    if not rows and warnings:
        status = "failed"
    error_text = "；".join(warnings)
    return _source_result(entry, slug, status, len(rows), error_text, elapsed, rows=rows)


def _source_result(
    entry: CompanyEntry | None,
    source: str,
    status: str,
    count: int,
    error: str,
    elapsed: float,
    *,
    rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "entry": entry,
        "source": source,
        "status": status,
        "count": count,
        "error": error,
        "elapsed": elapsed,
        "rows": rows or [],
    }


def _normalize_city(text: Any) -> str:
    value = re.sub(r"\s+", "", str(text or "")).lower()
    if value.endswith("市"):
        value = value[:-1]
    return value


def _city_decision(location: str, city: str) -> tuple[bool, bool]:
    """返回 (是否保留, 是否城市未知)。

    目标城市为空时保留所有岗位；目标城市非空而 location 为空时视为不匹配：
    keep=False, unknown=True（城市是硬筛，空 location 不能静默放行）。
    """
    target = _normalize_city(city)
    raw_location = str(location or "").strip()
    if not target:
        return True, False
    if not raw_location:
        return False, True
    normalized = _normalize_city(raw_location)
    if any(hint in normalized for hint in _REMOTE_HINTS):
        return True, False
    return target in normalized, False


async def _enrich_jobs(
    jd_results: list[dict[str, Any]],
    city: str,
    deadline: float,
    semaphore: asyncio.Semaphore,
    counts: dict[str, int],
) -> tuple[list[JDEvidence], dict[str, int]]:
    pending: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    seen_titles: set[tuple[str, str, str]] = set()
    now = datetime.now().isoformat()

    for result in jd_results:
        slug = result["source"]
        entry = result.get("entry")
        default_company = entry.name if entry is not None else slug
        for row in result["rows"]:
            title = str(row.get("title") or "").strip() or "未知岗位"
            company = str(row.get("company") or "").strip() or default_company
            location = str(row.get("location") or "").strip()
            list_only = str(row.get("detail_status") or "").strip() == "list_only"
            keep, unknown = _city_decision(location, city)
            if unknown:
                counts["unknown_city"] += 1
            if not keep:
                counts["dropped_city"] += 1
                # list-only 只豁免详情补抓/详情缺失剔除，不豁免城市硬筛；
                # 被城市硬筛剔除的 list-only 行仍要计入 list-only 缺口。
                if list_only:
                    counts["list_only"] += 1
                    counts["list_only_dropped_city"] += 1
                continue
            url = str(row.get("url") or "").strip()
            title_key = (_norm_text(company), _norm_text(title), _norm_text(location))
            if url:
                url_key = _url_key(url)
                if url_key in seen_urls:
                    continue
                seen_urls.add(url_key)
            else:
                if title_key in seen_titles:
                    continue
                seen_titles.add(title_key)
            pending.append(
                {
                    "slug": slug,
                    "entry": entry,
                    "company": company,
                    "title": title,
                    "location": location,
                    "salary": str(row.get("salary") or "").strip(),
                    "url": url,
                    "summary": str(row.get("summary") or row.get("snippet") or "").strip(),
                    "description": str(row.get("description") or "").strip(),
                    "requirements": str(row.get("requirements") or "").strip(),
                    "detail_status": str(row.get("detail_status") or "").strip(),
                    "fetched_at": str(row.get("fetched_at") or now),
                }
            )

    needs_detail: list[dict[str, Any]] = []
    kept: list[dict[str, Any]] = []
    for item in pending:
        # BOSS 研究阶段固定 list-only：只豁免详情补抓/详情缺失剔除（城市硬筛已在上游执行）。
        if item["detail_status"] == "list_only":
            # 保留行先入库；list_only / list_only_kept 在最终 jd_items 上重算。
            kept.append(item)
        elif item["description"] or item["requirements"]:
            item["detail_status"] = "ok"
            kept.append(item)
        elif item["url"]:
            needs_detail.append(item)
        else:
            counts["dropped_no_detail"] += 1

    if len(needs_detail) > MAX_DETAIL_FETCH:
        counts["dropped_no_detail"] += len(needs_detail) - MAX_DETAIL_FETCH
        needs_detail = needs_detail[:MAX_DETAIL_FETCH]

    detail_results = await asyncio.gather(
        *(
            _fetch_detail(item, deadline, semaphore)
            for item in needs_detail
        )
    )
    for item, detail in zip(needs_detail, detail_results, strict=True):
        if detail is None:
            counts["dropped_no_detail"] += 1
            continue
        item["description"] = detail["description"]
        item["requirements"] = detail["requirements"]
        item["detail_status"] = "ok"
        kept.append(item)

    evidence: list[JDEvidence] = []
    for item in kept:
        entry = item["entry"]
        if entry is not None:
            company_id, company, tier = entry.id, item["company"], entry.tier
        else:
            company_id, tier, catalog_name = _map_boss_company(item["company"])
            company = item["company"] or catalog_name
        evidence.append(
            JDEvidence(
                id="",
                company_id=company_id,
                company=company,
                tier=tier,
                title=item["title"],
                location=item["location"],
                salary=item["salary"],
                url=item["url"],
                summary=item["summary"],
                description=item["description"],
                requirements=item["requirements"],
                source=item["slug"],
                fetched_at=item["fetched_at"],
                detail_status=item.get("detail_status") or "ok",
                reused=False,
            )
        )
    return evidence, counts


async def _fetch_detail(
    item: dict[str, Any], deadline: float, semaphore: asyncio.Semaphore
) -> dict[str, str] | None:
    loop = asyncio.get_running_loop()
    async with semaphore:
        detail: Any = None
        for attempt in range(SOURCE_RETRY + 1):
            remaining = deadline - loop.time()
            if remaining <= 0:
                return None
            timeout = min(SOURCE_TIMEOUT, remaining)
            try:
                detail = await asyncio.wait_for(
                    asyncio.to_thread(get_job_detail, item["url"], company=item["slug"]),
                    timeout=timeout,
                )
                break
            except TimeoutError:
                if attempt >= SOURCE_RETRY or deadline - loop.time() <= 1:
                    return None
            except Exception:  # noqa: BLE001 - 详情失败按无详情剔除
                return None
    if not isinstance(detail, dict) or detail.get("error"):
        return None
    description = str(detail.get("description") or detail.get("content") or "").strip()
    requirements = str(detail.get("requirements") or "").strip()
    if not description and not requirements:
        return None
    return {"description": description, "requirements": requirements}


def _dedupe_jobs(items: list[JDEvidence]) -> list[JDEvidence]:
    seen_urls: set[str] = set()
    seen_titles: set[tuple[str, str, str]] = set()
    result: list[JDEvidence] = []
    for item in items:
        if item.url:
            key = _url_key(item.url)
            if key in seen_urls:
                continue
            seen_urls.add(key)
        else:
            key = (_norm_text(item.company), _norm_text(item.title), _norm_text(item.location))
            if key in seen_titles:
                continue
            seen_titles.add(key)
        result.append(item)
    return result


def _recompute_list_only_counts(
    counts: dict[str, int], final_jd: list[JDEvidence]
) -> None:
    """按最终 JD 集合重算 list-only 计数（去重/截断之后调用）。"""
    kept = sum(1 for item in final_jd if item.detail_status == "list_only")
    dropped_city = int(counts.get("list_only_dropped_city") or 0)
    counts["list_only_kept"] = kept
    counts["list_only_dropped_city"] = dropped_city
    counts["list_only"] = kept + dropped_city


def _truncate_per_company(items: list[JDEvidence], limit: int) -> list[JDEvidence]:
    """按企业截断抓取结果：多个 scraper 共享 per_company_limit 配额。"""
    kept: list[JDEvidence] = []
    counts: dict[str, int] = {}
    for item in items:
        key = item.company_id or _norm_text(item.company)
        current = counts.get(key, 0)
        if current >= limit:
            continue
        counts[key] = current + 1
        kept.append(item)
    return kept


def _research_round_label(profile: Any) -> str:
    research = getattr(profile, "research", None)
    if not isinstance(research, dict):
        return ""
    generated_at = str(research.get("generated_at") or "").strip()
    direction = str(research.get("direction") or research.get("role") or "").strip()
    city = str(research.get("city") or "").strip()
    bits = [part for part in (direction, city) if part]
    detail = f"（{' / '.join(bits)}）" if bits else ""
    return f"research {generated_at or '未知时间'}{detail}"


def _pool_has_company(name: str, pool: CompanyPool) -> bool:
    key = str(name or "").strip().lower()
    if not key:
        return False
    return any(key in {entry.id.lower(), entry.name.lower()} for entry in pool.companies)


def _reuse_jobs(
    profile: Any,
    pool: CompanyPool,
    city: str,
    counts: dict[str, int],
) -> tuple[list[JDEvidence], dict[str, int]]:
    samples, _cases, fresh = _research_samples(profile)
    if not fresh:
        return [], counts
    round_label = _research_round_label(profile)
    reused: list[JDEvidence] = []
    for sample in samples:
        company_raw = str(sample.get("company") or "").strip()
        title = str(sample.get("title") or "").strip()
        if not title:
            continue
        description = str(sample.get("description") or "").strip()
        requirements = str(sample.get("requirements") or "").strip()
        if not description and not requirements:
            continue
        location = str(sample.get("location") or "").strip()
        keep, unknown = _city_decision(location, city)
        if unknown:
            counts["unknown_city"] += 1
        if not keep:
            counts["dropped_city"] += 1
            continue
        company_id, company, tier = _match_company(company_raw, pool)
        in_pool = _pool_has_company(company_raw, pool)
        reused.append(
            JDEvidence(
                id="",
                company_id=company_id,
                company=company,
                tier=tier,
                title=title,
                location=location,
                salary=str(sample.get("salary") or "").strip(),
                url=str(sample.get("url") or "").strip(),
                summary=str(sample.get("snippet") or sample.get("summary") or "").strip(),
                description=description,
                requirements=requirements,
                source=str(sample.get("source") or "research").strip(),
                fetched_at=str(sample.get("fetched_at") or "").strip(),
                detail_status="ok",
                reused=True,
                reused_from=round_label,
                reused_pool_id=pool.meta.id if in_pool else "",
                reused_in_pool=in_pool,
            )
        )
    return reused, counts


def _merge_jobs(
    fresh: list[JDEvidence], reused: list[JDEvidence], limit: int
) -> list[JDEvidence]:
    result = list(fresh[:limit])
    fresh_urls = {_url_key(item.url) for item in result if item.url}
    fresh_titles = {(_norm_text(item.company), _norm_text(item.title)) for item in result}
    seen_urls: set[str] = set()
    seen_titles: set[tuple[str, str]] = set()
    for item in reused:
        if len(result) >= limit:
            break
        title_key = (_norm_text(item.company), _norm_text(item.title))
        url_key = _url_key(item.url)
        if url_key and (url_key in fresh_urls or url_key in seen_urls):
            continue
        if not url_key and (title_key in fresh_titles or title_key in seen_titles):
            continue
        if url_key:
            seen_urls.add(url_key)
        else:
            seen_titles.add(title_key)
        result.append(item)
    return result


async def _collect_interviews(
    target: TargetSpec,
    keyword: str,
    education: str,
    limit: int,
    deadline: float,
    semaphore: asyncio.Semaphore,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not keyword:
        return (
            [
                {
                    "source": "cases",
                    "scope": "cases",
                    "status": "failed",
                    "count": 0,
                    "error": "目标岗位与方向均为空，无法搜索面经",
                    "elapsed": 0.0,
                }
            ],
            [],
        )
    fallback_note = ""
    if not (target.role or "").strip():
        fallback_note = (
            f"目标岗位为空，面经已回退使用方向「{keyword}」"
            f" + 城市「{target.city or '不限'}」搜索"
        )
    loop = asyncio.get_running_loop()
    started = loop.time()
    async with semaphore:
        remaining = deadline - loop.time()
        if remaining <= 0:
            return (
                [
                    {
                        "source": "cases",
                        "scope": "cases",
                        "status": "failed",
                        "count": 0,
                        "error": "总预算耗尽，未执行面经抓取",
                        "elapsed": loop.time() - started,
                    }
                ],
                [],
            )
        timeout = min(SOURCE_TIMEOUT, remaining)
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    collect_cases,
                    role=keyword,
                    company="",
                    city=target.city,
                    education=education,
                    kind="both",
                    limit=limit,
                ),
                timeout=timeout,
            )
        except TimeoutError:
            return (
                [
                    {
                        "source": "cases",
                        "scope": "cases",
                        "status": "failed",
                        "count": 0,
                        "error": f"面经抓取超时（{timeout:.0f} 秒）",
                        "elapsed": timeout,
                    }
                ],
                [],
            )
        except Exception as exc:  # noqa: BLE001 - 面经失败不拖垮 JD
            return (
                [
                    {
                        "source": "cases",
                        "scope": "cases",
                        "status": "failed",
                        "count": 0,
                        "error": f"{type(exc).__name__}: {exc}",
                        "elapsed": loop.time() - started,
                    }
                ],
                [],
            )
    elapsed = loop.time() - started
    if not isinstance(result, dict):
        return (
            [
                {
                    "source": "cases",
                    "scope": "cases",
                    "status": "failed",
                    "count": 0,
                    "error": "面经抓取返回格式异常",
                    "elapsed": elapsed,
                }
            ],
            [],
        )

    warnings = [str(item) for item in result.get("warnings") or [] if str(item).strip()]
    sources = result.get("sources") if isinstance(result.get("sources"), dict) else {}
    cases = [item for item in result.get("cases") or [] if isinstance(item, dict)]
    statuses: list[dict[str, Any]] = []
    if sources:
        for source, raw_count in sources.items():
            count = _as_safe_int(raw_count)
            error = _warning_for(str(source), warnings)
            status = "ok" if count else ("failed" if error else "empty")
            statuses.append(
                {
                    "source": str(source),
                    "scope": "cases",
                    "status": status,
                    "count": count,
                    "error": error,
                    "elapsed": round(elapsed, 3),
                    "note": fallback_note,
                }
            )
    else:
        statuses.append(
            {
                "source": "cases",
                "scope": "cases",
                "status": "ok" if cases else ("failed" if warnings else "empty"),
                "count": len(cases),
                "error": "；".join(warnings),
                "elapsed": round(elapsed, 3),
                "note": fallback_note,
            }
        )
    return statuses, cases


def _warning_for(source: str, warnings: list[str]) -> str:
    for warning in warnings:
        if warning.startswith(f"{source}:"):
            return warning.split(":", 1)[1].strip()
    return ""


def _as_safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _to_interviews(cases: list[dict[str, Any]]) -> list[InterviewEvidence]:
    now = datetime.now().isoformat()
    result: list[InterviewEvidence] = []
    for case in cases:
        title = str(case.get("title") or "").strip()
        if not title:
            continue
        background = case.get("background") if isinstance(case.get("background"), dict) else {}
        company_raw = str(case.get("company") or background.get("company") or "").strip()
        company_id, company = _map_interview_company(company_raw)
        highlights = [str(item).strip() for item in case.get("highlights") or [] if str(item).strip()]
        result.append(
            InterviewEvidence(
                id="",
                company_id=company_id,
                company=company,
                title=title,
                source=str(case.get("source") or "").strip(),
                url=str(case.get("url") or "").strip(),
                education_tag=str(
                    case.get("education_tag") or background.get("education_tag") or ""
                ).strip(),
                year=str(case.get("year") or background.get("year") or "").strip(),
                highlights=highlights,
                content="\n".join(highlights),
                fetched_at=str(case.get("date") or now),
                reused=False,
            )
        )
    return result


def _map_interview_company(name: str) -> tuple[str, str]:
    if not name:
        return "", ""
    entry = catalog.get_company(name)
    if entry is None:
        return "", ""
    return str(entry["id"]), str(entry["name"])


def _dedupe_interviews(items: list[InterviewEvidence]) -> list[InterviewEvidence]:
    seen: set[tuple[str, ...]] = set()
    result: list[InterviewEvidence] = []
    for item in items:
        key = _interview_key(item)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _interview_key(item: InterviewEvidence) -> tuple[str, ...]:
    if item.url:
        return ("url", _url_key(item.url))
    return ("title", _norm_text(item.source), _norm_text(item.title))


def _reuse_interviews(profile: Any, pool: CompanyPool) -> list[InterviewEvidence]:
    _samples, cases, fresh = _research_samples(profile)
    if not fresh:
        return []
    round_label = _research_round_label(profile)
    now = datetime.now().isoformat()
    result: list[InterviewEvidence] = []
    for case in cases:
        title = str(case.get("title") or "").strip()
        if not title:
            continue
        company_raw = str(case.get("company") or "").strip()
        company_id, company = _map_interview_company(company_raw)
        in_pool = _pool_has_company(company_raw, pool)
        highlights = [str(item).strip() for item in case.get("highlights") or [] if str(item).strip()]
        result.append(
            InterviewEvidence(
                id="",
                company_id=company_id,
                company=company,
                title=title,
                source=str(case.get("source") or "").strip(),
                url=str(case.get("url") or "").strip(),
                education_tag=str(case.get("education_tag") or "").strip(),
                year=str(case.get("year") or "").strip(),
                highlights=highlights,
                content="\n".join(highlights),
                fetched_at=now,
                reused=True,
                reused_from=round_label,
                reused_pool_id=pool.meta.id if in_pool else "",
                reused_in_pool=in_pool,
            )
        )
    return result


def _merge_interviews(
    fresh: list[InterviewEvidence], reused: list[InterviewEvidence], limit: int
) -> list[InterviewEvidence]:
    result = list(fresh[:limit])
    seen = {_interview_key(item) for item in result}
    for item in reused:
        if len(result) >= limit:
            break
        key = _interview_key(item)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _research_samples(profile: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
    research = getattr(profile, "research", None)
    if not isinstance(research, dict) or not research:
        return [], [], False
    generated = _parse_datetime(research.get("generated_at"))
    if generated is None:
        return [], [], False
    now = datetime.now(generated.tzinfo) if generated.tzinfo else datetime.now()
    if now - generated > timedelta(days=RESEARCH_TTL_DAYS):
        return [], [], False
    jd_samples = [item for item in research.get("jd_samples") or [] if isinstance(item, dict)]
    cases = [item for item in research.get("cases") or [] if isinstance(item, dict)]
    return jd_samples, cases, True


def _parse_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _assign_ids(items: list[JDEvidence] | list[InterviewEvidence], prefix: str) -> None:
    for index, item in enumerate(items, 1):
        item.id = f"{prefix}{index:03d}"


def _confidence(sample_size: int, *, low: int, medium: int) -> str:
    if sample_size < low:
        return "low"
    if sample_size < medium:
        return "medium"
    return "high"


def _build_gaps(
    pool: CompanyPool,
    source_status: list[dict[str, Any]],
    counts: dict[str, int],
    confidence: dict[str, str],
    city: str,
    *,
    jd_items: list[JDEvidence] | None = None,
    interview_items: list[InterviewEvidence] | None = None,
    irrelevant_samples: list[str] | None = None,
) -> list[str]:
    gaps: list[str] = []
    unscrapable = [
        entry.name for entry in pool.companies if entry.status != "excluded" and not entry.scrapable
    ]
    if unscrapable:
        gaps.append("未接入自动抓取（已跳过）：" + "、".join(unscrapable))
    for status in source_status:
        scope = "面经" if status.get("scope") == "cases" else "JD"
        if status.get("status") == "failed":
            detail = str(status.get("error") or "未知错误")
            gaps.append(f"{scope}来源 {status.get('source')} 失败：{detail}")
        elif status.get("status") == "empty":
            gaps.append(f"{scope}来源 {status.get('source')} 无结果")
        note = str(status.get("note") or "").strip()
        if note:
            gaps.append(note)
    if counts.get("dropped_irrelevant"):
        samples = [title for title in irrelevant_samples or [] if title]
        sample_text = "、".join(samples[:10])
        if len(samples) > 10:
            sample_text += " 等"
        gaps.append(
            f"岗位相关性过滤剔除 {counts['dropped_irrelevant']} 条 JD"
            f"（标题/正文未命中目标岗位关键词）"
            + (f"，样本：{sample_text}" if sample_text else "")
        )
    if counts["dropped_city"]:
        gaps.append(f"城市硬筛剔除 {counts['dropped_city']} 条 JD（目标城市：{city or '不限'}）")
    if counts.get("unknown_city"):
        gaps.append(
            f"其中 {counts['unknown_city']} 条 JD 地点未知（空 location），"
            "已按城市硬筛剔除并计入未知城市缺口"
        )
    if counts["dropped_no_detail"]:
        gaps.append(f"缺少岗位详情剔除 {counts['dropped_no_detail']} 条 JD")
    if counts.get("list_only_kept", counts.get("list_only")):
        gaps.append(
            "BOSS 直聘 list-only 保留 "
            f"{counts.get('list_only_kept', counts.get('list_only', 0))} 条"
            "（仅列表字段，未补详情）"
        )
    if counts.get("list_only_dropped_city"):
        gaps.append(
            f"BOSS 直聘 list-only 有 {counts['list_only_dropped_city']} 条因城市硬筛剔除"
            "（list-only 仅豁免详情补抓，不豁免城市硬筛）"
        )
    if counts.get("reused_outside_pool"):
        outside_jd = [
            item.title for item in (jd_items or []) if item.reused and not item.reused_in_pool
        ]
        outside_interviews = [
            item.title
            for item in (interview_items or [])
            if item.reused and not item.reused_in_pool
        ]
        samples = "、".join((outside_jd + outside_interviews)[:10])
        gaps.append(
            f"池外复用 {counts['reused_outside_pool']} 条历史样本"
            f"（JD {counts.get('reused_jd_outside_pool', 0)} 条 / "
            f"面经 {counts.get('reused_interviews_outside_pool', 0)} 条），"
            "不属于本次企业池"
            + (f"，样本：{samples}" if samples else "")
        )
    if not counts["kept_jobs"]:
        gaps.append("未采集到任何 JD")
    if not counts["interviews"]:
        gaps.append("未采集到面经")
    if counts["kept_jobs"] and confidence["jd"] == "low":
        gaps.append(f"JD 样本 {counts['kept_jobs']} 条，置信度 low（<15 条），结论仅作方向参考")
    if counts["interviews"] and confidence["interview"] == "low":
        gaps.append(
            f"面经样本 {counts['interviews']} 条，置信度 low（<10 条），结论仅作方向参考"
        )
    return gaps


def _match_company(name: str, pool: CompanyPool) -> tuple[str, str, str]:
    key = (name or "").strip().lower()
    if key:
        for entry in pool.companies:
            if key in {entry.id.lower(), entry.name.lower()}:
                return entry.id, entry.name, entry.tier
    entry = catalog.get_company(name) if name else None
    if entry is not None:
        return str(entry["id"]), str(entry["name"]), str(entry["tier"])
    return "", name, ""


def _map_boss_company(name: str) -> tuple[str, str, str]:
    """BOSS 公司名映射企业目录；映射不到时档位标「未收录」，不硬猜。"""
    entry = catalog.get_company(name) if name else None
    if entry is None:
        return "", "未收录", name
    return str(entry["id"]), str(entry["tier"] or "未收录"), str(entry["name"])


def _url_key(url: str) -> str:
    return str(url or "").strip().rstrip("/").lower()


def _norm_text(text: Any) -> str:
    return re.sub(r"\s+", "", str(text or "")).lower()


def _update_core_state(profile_name: str, artifact_id: str) -> None:
    profile = load_profile(profile_name)
    core_state = dict(profile.core_state or {})
    core_state.update(
        {
            "evidence_run_id": artifact_id,
            "stage": STAGE_ID,
            "updated_at": datetime.now().isoformat(),
        }
    )
    profile.core_state = core_state
    save_profile(profile, profile_name)


__all__ = [
    "CONCURRENCY",
    "DEFAULT_MAX_COMPANIES",
    "DEFAULT_MAX_INTERVIEWS",
    "DEFAULT_MAX_JD",
    "DEFAULT_PER_COMPANY_LIMIT",
    "MAX_DETAIL_FETCH",
    "PRODUCES",
    "REQUIRES",
    "RESEARCH_TTL_DAYS",
    "SOURCE_TIMEOUT",
    "STAGE_ID",
    "TOTAL_BUDGET",
    "run",
    "run_async",
    "validate",
]
