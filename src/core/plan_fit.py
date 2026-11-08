"""计划失配检测器——判断旧计划是否仍适合新证据。

只读档案与 artifact：不写档案、不改计划、不调用 LLM。
代码负责事实（证据新鲜度、链路一致性、要求覆盖率、任务匹配、漏斗样本），
LLM 只负责把 signal 转成给用户的一句询问（question_for_user）。

状态口径：
- aligned：无 medium/high 信号；
- minor_drift：只有 medium 信号；
- major_drift：存在 high 信号；
- stale_evidence：只有证据过期这一条 medium 信号；
- incomplete_chain：档案还没有建立企业对齐链路（无证据/需求/执行方案）。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from ..models import CareerProfile
from ..tools.application_tracker import funnel_stats
from ..tools.profile import load_profile
from .artifacts.store import ArtifactStore
from .orchestrator import state_machine
from .progress import STAGE_KEYS

STALE_EVIDENCE_DAYS = 7
FUNNEL_MIN_SAMPLE = 5
FUNNEL_LOW_SCREEN_RATE = 0.25
MAX_UNCOVERED_REQUIREMENTS = 10
MAX_INTERVIEW_TOPICS = 5

TRIGGERS = ("manual", "evidence_refresh", "milestone", "weekly_review")

_QUESTIONS = {
    "rerun_gap": "目标或差距依据已经变了，要不要先重新做一次差距分析，再决定是否调整计划？",
    "rerun_alignment": "现有计划和企业最新需求有出入，要不要按最新证据重新校准执行方案？",
    "refresh_evidence": "证据已经超过 7 天，要不要先刷新一次岗位与面经样本，再判断计划要不要改？",
    "review": "投递漏斗显示初筛通过偏低，要不要先做一次周检视复盘，再决定是否改计划？",
}

_SEVERITIES = ("high", "medium", "info")


def check_plan_fit(profile_name: str, trigger: str = "manual") -> dict[str, Any]:
    """检测旧计划是否仍适合新证据；返回信号与给用户的询问，不修改任何数据。"""
    trigger = trigger if trigger in TRIGGERS else "manual"
    profile = load_profile(profile_name)
    store = ArtifactStore()
    core_state = profile.core_state if isinstance(profile.core_state, dict) else {}

    pool = _latest(store, profile_name, state_machine.STAGE_COMPANY_POOL, core_state)
    evidence = _latest(store, profile_name, state_machine.STAGE_EVIDENCE, core_state)
    requirement = _latest(store, profile_name, state_machine.STAGE_REQUIREMENT, core_state)
    plan = _latest(store, profile_name, state_machine.STAGE_EXECUTION_PLAN, core_state)

    artifact_ids = {
        "company_pool_id": _artifact_id(pool),
        "evidence_run_id": _artifact_id(evidence),
        "requirement_profile_id": _artifact_id(requirement),
        "execution_plan_id": _artifact_id(plan),
    }

    incomplete = evidence is None and requirement is None and plan is None
    signals: list[dict[str, Any]] = []
    if incomplete:
        signals.append(
            _signal(
                "incomplete_chain",
                "info",
                _incomplete_message(pool),
            )
        )
    else:
        signals.extend(_stale_evidence(evidence))
        signals.extend(_alignment_missing(evidence, plan))
        signals.extend(_plan_not_applied(plan))
        signals.extend(_alignment_stale(evidence, requirement, plan))
        corpus = _task_corpus(profile)
        signals.extend(_uncovered_requirements(requirement, corpus))
        signals.extend(_uncovered_interview_topics(requirement, corpus))
        signals.extend(_goal_changed(profile))
        signals.extend(_funnel_signal(profile))
        signals.extend(_insufficient_sample(requirement, evidence))

    status = _status(incomplete, signals)
    action, next_tool = _recommend(
        status,
        signals,
        incomplete=incomplete,
        has_pool=pool is not None,
        has_requirement=requirement is not None,
    )
    question = "" if status in ("aligned", "incomplete_chain") else _QUESTIONS.get(action, "")

    return {
        "status": status,
        "trigger": trigger,
        "checked_at": datetime.now().isoformat(),
        "signals": signals,
        "recommended_action": action,
        "next_tool": next_tool,
        "question_for_user": question,
        "artifact_ids": artifact_ids,
    }


def _latest(
    store: ArtifactStore,
    profile_name: str,
    stage: str,
    core_state: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """只按 core_state 指针解析；不无条件回退 latest，避免读取无关旧 artifact。"""
    state = core_state if isinstance(core_state, dict) else {}
    artifact_id = str(state.get(STAGE_KEYS.get(stage, "")) or "")
    if not artifact_id:
        return None
    data = store.load(artifact_id)
    return data if _matches_stage(data, stage, profile_name) else None


def _matches_stage(
    data: dict[str, Any] | None, stage: str, profile_name: str
) -> bool:
    if not isinstance(data, dict):
        return False
    meta = data.get("meta")
    if not isinstance(meta, dict) or meta.get("stage") != stage:
        return False
    return str(meta.get("profile_name") or "") == profile_name


def _artifact_id(artifact: dict[str, Any] | None) -> str:
    if not isinstance(artifact, dict):
        return ""
    meta = artifact.get("meta")
    return str(meta.get("id") or "") if isinstance(meta, dict) else ""


def _meta(artifact: dict[str, Any]) -> dict[str, Any]:
    meta = artifact.get("meta")
    return meta if isinstance(meta, dict) else {}


def _parse_dt(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None


def _now_for(dt: datetime) -> datetime:
    return datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()


def _signal(
    code: str,
    severity: str,
    message: str,
    evidence_ids: list[str] | None = None,
    task_ids: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity if severity in _SEVERITIES else "info",
        "message": message,
        "evidence_ids": _clean_ids(evidence_ids),
        "task_ids": _clean_ids(task_ids),
    }


def _clean_ids(raw: Any) -> list[str]:
    if not isinstance(raw, (list, tuple, set)):
        return []
    seen: set[str] = set()
    result: list[str] = []
    for item in raw:
        text = str(item).strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _incomplete_message(pool: dict[str, Any] | None) -> str:
    if pool is None:
        return (
            "尚未建立企业对齐链路（没有 CompanyPool / EvidenceRun / "
            "RequirementProfile / ExecutionPlan），无法判断计划是否失配。"
        )
    return (
        "已有目标企业池，但还没有岗位证据、需求画像与执行方案，"
        "无法判断计划是否失配；可先采集企业证据。"
    )


def _stale_evidence(evidence: dict[str, Any] | None) -> list[dict[str, Any]]:
    if evidence is None:
        return []
    created = _parse_dt(_meta(evidence).get("created_at"))
    if created is None:
        return []
    age = _now_for(created) - created
    if age <= timedelta(days=STALE_EVIDENCE_DAYS):
        return []
    days = max(0, age.days)
    return [
        _signal(
            "stale_evidence",
            "medium",
            f"证据采集于 {days} 天前（超过 {STALE_EVIDENCE_DAYS} 天），"
            "岗位与面经样本可能已过期，建议先刷新证据再判断计划。",
            evidence_ids=[_artifact_id(evidence)],
        )
    ]


def _alignment_missing(
    evidence: dict[str, Any] | None, plan: dict[str, Any] | None
) -> list[dict[str, Any]]:
    if evidence is None or plan is not None:
        return []
    return [
        _signal(
            "alignment_missing",
            "high",
            "已有岗位与面经证据，但还没有执行版方案（ExecutionPlan）；"
            "旧计划未按企业需求校准，建议重新对齐。",
            evidence_ids=[_artifact_id(evidence)],
        )
    ]


def _plan_not_applied(plan: dict[str, Any] | None) -> list[dict[str, Any]]:
    if plan is None or bool(plan.get("applied")):
        return []
    return [
        _signal(
            "plan_not_applied",
            "high",
            "执行版方案已生成但尚未应用，当前计划仍是旧版本，不能视为已对齐；"
            "建议确认并应用执行版方案。",
            evidence_ids=[_artifact_id(plan)],
        )
    ]


def _alignment_stale(
    evidence: dict[str, Any] | None,
    requirement: dict[str, Any] | None,
    plan: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if plan is None:
        return []
    if requirement is None:
        return [
            _signal(
                "alignment_stale",
                "high",
                "执行版方案存在但找不到对应的需求画像（RequirementProfile），"
                "无法核对计划与需求是否一致，建议重新校准。",
                evidence_ids=[_artifact_id(evidence)],
            )
        ]

    reasons: list[str] = []
    referenced = str(plan.get("requirement_profile_id") or "").strip()
    latest_requirement_id = _artifact_id(requirement)
    if referenced and referenced != latest_requirement_id:
        reasons.append("执行方案引用的需求画像不是最新版本")

    evidence_created = _parse_dt(_meta(evidence).get("created_at")) if evidence else None
    plan_created = _parse_dt(_meta(plan).get("created_at"))
    if (
        evidence_created is not None
        and plan_created is not None
        and evidence_created > plan_created
    ):
        reasons.append("证据采集时间晚于执行方案保存时间")

    if not reasons:
        return []
    return [
        _signal(
            "alignment_stale",
            "high",
            "执行方案已与最新事实脱节：" + "；".join(reasons) + "。建议按最新证据重新校准。",
            evidence_ids=[_artifact_id(evidence)],
            task_ids=[],
        )
    ]


def _task_corpus(profile: CareerProfile) -> str:
    parts: list[str] = []
    for task in profile.tasks:
        parts.append(task.name)
        parts.append(task.description)
        parts.extend(str(item) for item in task.how_to)
        parts.append(task.done_criteria)
    roadmap = _roadmap_of(profile.plan)
    for phase in _as_list(roadmap.get("phases")):
        if not isinstance(phase, dict):
            continue
        for milestone in _as_list(phase.get("milestones")):
            if not isinstance(milestone, dict):
                continue
            for task in _as_list(milestone.get("tasks")):
                if not isinstance(task, dict):
                    continue
                parts.append(str(task.get("name") or ""))
                parts.append(str(task.get("description") or ""))
    return "\n".join(part for part in parts if part).lower()


def _roadmap_of(plan: Any) -> dict[str, Any]:
    if not isinstance(plan, dict):
        return {}
    inner = plan.get("roadmap")
    if isinstance(inner, dict) and "phases" in inner:
        return inner
    return plan if "phases" in plan else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _corpus_contains(corpus: str, term: str) -> bool:
    return bool(term) and term.strip().lower() in corpus


def _requirement_severity(confidence: str, company_count: int) -> str:
    if confidence == "low":
        return "info"
    return "high" if company_count >= 2 else "medium"


def _uncovered_requirements(
    requirement: dict[str, Any] | None, corpus: str
) -> list[dict[str, Any]]:
    if requirement is None:
        return []
    confidence = str(requirement.get("confidence_jd") or "low").strip().lower()
    signals: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in _as_list(requirement.get("high_frequency"))[:MAX_UNCOVERED_REQUIREMENTS]:
        if not isinstance(item, dict):
            continue
        term = str(item.get("term") or "").strip()
        if not term or term in seen or _corpus_contains(corpus, term):
            continue
        seen.add(term)
        company_count = _as_int(item.get("company_count"))
        jd_count = _as_int(item.get("jd_count"))
        severity = _requirement_severity(confidence, company_count)
        if severity == "info":
            message = (
                f"高频要求「{term}」在现有任务中尚未体现；但 JD 样本置信度为 low，"
                "先作观察，不据此判定计划失配。"
            )
        else:
            message = (
                f"高频要求「{term}」在现有任务中找不到对应练习"
                f"（{jd_count} 条 JD / {company_count} 家公司），计划可能未覆盖。"
            )
        signals.append(
            _signal(
                "uncovered_requirement",
                severity,
                message,
                evidence_ids=item.get("evidence_ids"),
            )
        )
    return signals


def _uncovered_interview_topics(
    requirement: dict[str, Any] | None, corpus: str
) -> list[dict[str, Any]]:
    if requirement is None:
        return []
    known_terms = {
        str(item.get("term") or "").strip()
        for item in _as_list(requirement.get("high_frequency"))
        if isinstance(item, dict)
    }
    signals: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in _as_list(requirement.get("interview_topics"))[:MAX_INTERVIEW_TOPICS]:
        if not isinstance(item, dict):
            continue
        term = str(item.get("term") or "").strip()
        if (
            not term
            or term in seen
            or term in known_terms
            or _corpus_contains(corpus, term)
        ):
            continue
        seen.add(term)
        signals.append(
            _signal(
                "uncovered_interview_topic",
                "medium",
                f"面经高频考点「{term}」在现有任务中找不到对应准备，建议补进计划。",
                evidence_ids=item.get("evidence_ids"),
            )
        )
    return signals


def _goal_changed(profile: CareerProfile) -> list[dict[str, Any]]:
    reasons: list[str] = []
    if str(profile.gap_stale_at or "").strip():
        reasons.append("更换目标 JD 后差距分析尚未重做")

    want_updated = _parse_dt((profile.section_updated_at or {}).get("want"))
    plan_saved = _parse_dt(profile.plan_saved_at)
    if want_updated is not None and plan_saved is not None and want_updated > plan_saved:
        reasons.append("目标（want）在计划保存后更新过")

    if not reasons:
        return []
    return [
        _signal(
            "goal_changed",
            "high",
            "目标已变化：" + "；".join(reasons) + "。旧计划可能不再适合新目标，建议重跑差距分析。",
        )
    ]


def _funnel_signal(profile: CareerProfile) -> list[dict[str, Any]]:
    stats = funnel_stats(profile)
    total = _as_int(stats.get("total"))
    if total < FUNNEL_MIN_SAMPLE:
        return []
    rate = (stats.get("rates") or {}).get("screen")
    if rate is None or rate > FUNNEL_LOW_SCREEN_RATE:
        return []
    screened = _as_int(stats.get("screened"))
    percent = int(round(float(rate) * 100))
    return [
        _signal(
            "funnel_signal",
            "medium",
            f"已投递 {total} 家，仅 {screened} 家进初筛/面试（{percent}%），"
            "初筛通过偏低；建议先做周检视复盘简历与投递策略，不直接改计划。",
        )
    ]


def _insufficient_sample(
    requirement: dict[str, Any] | None, evidence: dict[str, Any] | None
) -> list[dict[str, Any]]:
    if requirement is not None:
        jd = str(requirement.get("confidence_jd") or "low").strip().lower()
        interview = str(requirement.get("confidence_interview") or "low").strip().lower()
    elif evidence is not None:
        confidence = evidence.get("confidence")
        confidence = confidence if isinstance(confidence, dict) else {}
        jd = str(confidence.get("jd") or "low").strip().lower()
        interview = str(confidence.get("interview") or "low").strip().lower()
    else:
        return []
    if jd != "low" or interview != "low":
        return []
    return [
        _signal(
            "insufficient_sample",
            "info",
            "JD 与面经样本置信度均为 low（样本不足），先补样本再判断计划是否失配，"
            "不要据此下全局结论。",
            evidence_ids=[_artifact_id(evidence)],
        )
    ]


def _status(incomplete: bool, signals: list[dict[str, Any]]) -> str:
    if incomplete:
        return "incomplete_chain"
    if any(signal["severity"] == "high" for signal in signals):
        return "major_drift"
    mediums = [signal for signal in signals if signal["severity"] == "medium"]
    if not mediums:
        return "aligned"
    if {signal["code"] for signal in mediums} == {"stale_evidence"}:
        return "stale_evidence"
    return "minor_drift"


def _recommend(
    status: str,
    signals: list[dict[str, Any]],
    *,
    incomplete: bool,
    has_pool: bool,
    has_requirement: bool,
) -> tuple[str, str]:
    if incomplete:
        return ("refresh_evidence", "collect_company_evidence") if has_pool else ("continue", "")

    codes = {signal["code"] for signal in signals}
    if "goal_changed" in codes:
        return "rerun_gap", "analyze_gaps"
    if "plan_not_applied" in codes:
        return "rerun_alignment", "save_execution_alignment"
    if "alignment_stale" in codes:
        return "rerun_alignment", "plan_execution_alignment"
    if "alignment_missing" in codes:
        if not has_requirement:
            return "rerun_alignment", "analyze_company_requirements"
        return "rerun_alignment", "plan_execution_alignment"
    if any(
        signal["code"] == "uncovered_requirement" and signal["severity"] == "high"
        for signal in signals
    ):
        return "rerun_alignment", "plan_execution_alignment"
    if "stale_evidence" in codes:
        return "refresh_evidence", "collect_company_evidence"
    if "funnel_signal" in codes:
        return "review", "get_weekly_review"
    if any(
        signal["code"] == "uncovered_interview_topic" and signal["severity"] == "medium"
        for signal in signals
    ):
        return "rerun_alignment", "plan_execution_alignment"
    if "insufficient_sample" in codes and status != "aligned":
        return "refresh_evidence", "collect_company_evidence"
    return "continue", ""


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


__all__ = [
    "FUNNEL_LOW_SCREEN_RATE",
    "FUNNEL_MIN_SAMPLE",
    "MAX_INTERVIEW_TOPICS",
    "MAX_UNCOVERED_REQUIREMENTS",
    "STALE_EVIDENCE_DAYS",
    "TRIGGERS",
    "check_plan_fit",
]
