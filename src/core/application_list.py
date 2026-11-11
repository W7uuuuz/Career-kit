"""投递清单：用证据池批量筛选、打分、排序投递目标。

这不是新的分析阶段，而是把 EvidenceRun（真实 JD）转成可跟进的投递候选：

- 城市是硬筛选；方向、技能、学历、档位、薪资是软打分；
- 数字与排序全部由代码计算，LLM 只负责解释；不编造岗位；
- 已投递（company + title 与 profile.applications 匹配）默认不重复推荐；
- 候选写入 ApplicationState.candidates，报告落盘为 md/json 两件套。
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from .. import education
from ..tools.application_tracker import funnel_stats
from ..tools.profile import load_profile
from .artifacts.models import (
    ApplicationCandidate,
    ApplicationState,
    ArtifactMeta,
    EvidenceRun,
    JDEvidence,
    RequirementProfile,
    TargetSpec,
)
from .artifacts.store import ArtifactStore
from .orchestrator import state_machine
from .reporting.application_report import save_report
from .sync import KEY_APPLICATIONS, STAGE_APPLICATIONS, merge_core_state

DEFAULT_TOP = 30
DEFAULT_MIN_SCORE = 0

_REMOTE_HINTS = ("远程", "全国", "不限", "remote", "anywhere")

# 中文岗位方向词表 + 常见英文方向词；只做字面命中，不做语义推断。
_ROLE_VOCAB: tuple[str, ...] = (
    "开发",
    "工程师",
    "算法",
    "前端",
    "后端",
    "全栈",
    "服务端",
    "客户端",
    "移动端",
    "数据",
    "分析",
    "分析师",
    "产品",
    "运营",
    "测试",
    "设计",
    "架构",
    "运维",
    "安全",
    "研发",
    "研究",
    "大模型",
    "人工智能",
    "机器学习",
    "深度学习",
    "推荐",
    "搜索",
    "广告",
    "增长",
    "风控",
    "量化",
    "嵌入式",
    "硬件",
    "电子",
    "电气",
    "机械",
    "能源",
    "财务",
    "人力",
    "销售",
    "市场",
    "客户",
    "实施",
    "交付",
    "解决方案",
    "售前",
    "售后",
    "项目",
    "管理",
    "游戏",
    "图形",
    "音视频",
    "通信",
    "芯片",
    "半导体",
    "实习",
    "agent",
    "ai",
    "llm",
    "rag",
    "python",
    "java",
    "go",
    "sql",
    "data",
    "backend",
    "frontend",
    "fullstack",
    "product",
    "operations",
    "algorithm",
    "machine",
    "learning",
    "developer",
    "engineer",
)

_ASCII_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#.\-]*")
_CJK_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]{2,}")
_SKILL_SPLIT_RE = re.compile(r"[,，、;；/\s]+")

_DEGREE_RANK = {"专科": 0, "本科": 1, "硕士": 2, "博士": 3}
_TIER_RANK = {"双非": 1, "211": 2, "985": 3}


class MissingEvidenceError(Exception):
    """没有可用 EvidenceRun 时抛出，由工具层转成 MISSING_DATA。"""


def run(
    profile_name: str,
    city: str = "",
    role: str = "",
    top: int = DEFAULT_TOP,
    min_score: int = DEFAULT_MIN_SCORE,
    include_applied: bool = False,
) -> dict[str, Any]:
    """生成投递清单并落盘；返回可序列化的结果。"""
    profile = load_profile(profile_name)
    store = ArtifactStore()
    evidence = _resolve_evidence(store, profile, profile_name)
    if evidence is None:
        raise MissingEvidenceError(
            "尚未采集岗位与面经证据，无法生成投递清单。先调用 collect_company_evidence 生成证据池。"
        )
    requirement = _resolve_requirement(store, profile, profile_name)
    target = _resolve_target(evidence, profile, city=city, role=role)

    user_skills = _user_skills(profile)
    user_education = _user_education(profile)
    demand_terms = _demand_terms(requirement)
    applied_keys = _applied_keys(profile)

    scored: list[tuple[int, int, ApplicationCandidate]] = []
    total_scored = 0
    dropped_city = 0
    unknown_city = 0
    for order, job in enumerate(evidence.jd_items):
        keep, job_unknown_city = _city_keep(job.location, target.city)
        if job_unknown_city:
            unknown_city += 1
        if not keep:
            dropped_city += 1
            continue
        status = _candidate_status(job, applied_keys)
        if status == "applied" and not include_applied:
            continue
        total_scored += 1
        score, reasons, gaps = _score_job(
            job,
            target=target,
            user_skills=user_skills,
            user_education=user_education,
            demand_terms=demand_terms,
            unknown_city=job_unknown_city,
        )
        candidate = _make_candidate(job, order, score, reasons, gaps, status)
        scored.append((score, order, candidate))

    scored.sort(key=lambda item: (-item[0], item[2].company, item[2].title, item[1]))
    ranked = _dedupe_candidates([item[2] for item in scored])

    limit = max(1, int(top or DEFAULT_TOP))
    threshold = max(0, int(min_score or 0))
    selected = [candidate for candidate in ranked if candidate.match_score >= threshold][:limit]
    for index, candidate in enumerate(selected, 1):
        candidate.id = f"APP{index:03d}"

    direction = target.role or "投递清单"
    report_paths = save_report(
        selected,
        profile_name,
        direction,
        evidence_run_id=evidence.meta.id,
        requirement_profile_id=requirement.meta.id if requirement else "",
        city=target.city,
        role=target.role,
        total_scored=total_scored,
    )
    artifact_id = _save_state(
        profile_name,
        profile,
        selected,
        evidence_run_id=evidence.meta.id,
        requirement_profile_id=requirement.meta.id if requirement else "",
        city=target.city,
        role=target.role,
        total_scored=total_scored,
    )

    return {
        "status": "ok",
        "profile_name": profile_name,
        "artifact_id": artifact_id,
        "direction": direction,
        "city": target.city,
        "role": target.role,
        "evidence_run_id": evidence.meta.id,
        "requirement_profile_id": requirement.meta.id if requirement else "",
        "candidate_count": len(selected),
        "total_scored": total_scored,
        "dropped_city": dropped_city,
        "unknown_city": unknown_city,
        "min_score": threshold,
        "top": [candidate.model_dump() for candidate in selected[:10]],
        "candidates": [candidate.model_dump() for candidate in selected],
        "report_paths": report_paths,
        "next_tools": ["record_application", "get_next_tasks"],
        "next_step": (
            "挑选候选后调用 record_application 记录真实投递；"
            "需要结合执行计划时调用 get_next_tasks。"
        ),
    }


def _resolve_evidence(
    store: ArtifactStore, profile: Any, profile_name: str
) -> EvidenceRun | None:
    state = profile.core_state if isinstance(profile.core_state, dict) else {}
    candidate_ids = [str(state.get("evidence_run_id") or "")]
    for artifact_id in candidate_ids:
        if not artifact_id:
            continue
        data = store.load(artifact_id)
        evidence = _as_evidence(data, profile_name)
        if evidence is not None:
            return evidence
    evidence = _as_evidence(store.latest(profile_name, state_machine.STAGE_EVIDENCE), profile_name)
    return evidence


def _as_evidence(data: Any, profile_name: str) -> EvidenceRun | None:
    if not isinstance(data, dict):
        return None
    meta = data.get("meta")
    if not isinstance(meta, dict):
        return None
    if meta.get("stage") != state_machine.STAGE_EVIDENCE:
        return None
    if str(meta.get("profile_name") or "") != profile_name:
        return None
    try:
        return EvidenceRun.model_validate(data)
    except Exception:
        return None


def _resolve_requirement(
    store: ArtifactStore, profile: Any, profile_name: str
) -> RequirementProfile | None:
    state = profile.core_state if isinstance(profile.core_state, dict) else {}
    artifact_id = str(state.get("requirement_profile_id") or "")
    data = store.load(artifact_id) if artifact_id else None
    requirement = _as_requirement(data, profile_name)
    if requirement is not None:
        return requirement
    return _as_requirement(
        store.latest(profile_name, state_machine.STAGE_REQUIREMENT), profile_name
    )


def _as_requirement(data: Any, profile_name: str) -> RequirementProfile | None:
    if not isinstance(data, dict):
        return None
    meta = data.get("meta")
    if not isinstance(meta, dict):
        return None
    if meta.get("stage") != state_machine.STAGE_REQUIREMENT:
        return None
    if str(meta.get("profile_name") or "") != profile_name:
        return None
    try:
        return RequirementProfile.model_validate(data)
    except Exception:
        return None


def _resolve_target(
    evidence: EvidenceRun, profile: Any, *, city: str = "", role: str = ""
) -> TargetSpec:
    target = evidence.target_spec.model_copy(deep=True)
    want = profile.want if isinstance(profile.want, dict) else {}
    who = profile.who if isinstance(profile.who, dict) else {}
    if not target.role:
        target.role = str(want.get("target_role") or want.get("direction") or "")
    if not target.city:
        target.city = str(want.get("city") or who.get("city") or "")
    if not target.target_tiers:
        target.target_tiers = _as_str_list(want.get("target_tiers"))
    if not target.bridge_tiers:
        target.bridge_tiers = _as_str_list(want.get("bridge_tiers"))
    if city.strip():
        target.city = city.strip()
    if role.strip():
        target.role = role.strip()
    return target


def _score_job(
    job: JDEvidence,
    *,
    target: TargetSpec,
    user_skills: list[str],
    user_education: str,
    demand_terms: list[str],
    unknown_city: bool,
) -> tuple[int, list[str], list[str]]:
    reasons: list[str] = []
    gaps: list[str] = []
    score = 0

    role_score, matched_role, role_tokens = _role_score(job, target.role)
    score += role_score
    if matched_role:
        reasons.append(f"方向命中：{'、'.join(matched_role)}")
    elif role_tokens:
        gaps.append(f"方向未命中：{target.role}")

    city_score, city_reason, city_gap = _city_score(job.location, target.city, unknown_city)
    score += city_score
    if city_reason:
        reasons.append(city_reason)
    if city_gap:
        gaps.append(city_gap)

    skill_score, skill_reason, skill_gap = _skill_score(job, user_skills)
    score += skill_score
    if skill_reason:
        reasons.append(skill_reason)
    if skill_gap:
        gaps.append(skill_gap)

    edu_score, edu_reason, edu_gap = _education_score(job, user_education)
    score += edu_score
    if edu_reason:
        reasons.append(edu_reason)
    if edu_gap:
        gaps.append(edu_gap)

    tier_score, tier_reason, tier_gap = _tier_score(job.tier, target)
    score += tier_score
    if tier_reason:
        reasons.append(tier_reason)
    if tier_gap:
        gaps.append(tier_gap)

    if job.salary.strip():
        score += 5
        reasons.append("已标注薪资")
    else:
        gaps.append("未标注薪资")

    missing_terms = _missing_demand_terms(job, demand_terms)
    if missing_terms:
        gaps.append(f"未覆盖高频要求：{'、'.join(missing_terms)}")

    return min(100, score), reasons, gaps


def _role_score(job: JDEvidence, role: str) -> tuple[int, list[str], list[str]]:
    tokens = _role_tokens(role)
    if not tokens:
        return 0, [], []
    text = f"{job.title} {job.summary}".lower()
    matched = [token for token in tokens if token in text]
    if not matched:
        return 0, [], tokens
    return round(40 * len(matched) / len(tokens)), matched, tokens


def _role_tokens(role: str) -> list[str]:
    text = str(role or "").strip()
    if not text:
        return []
    low = text.lower()
    tokens: list[str] = [word for word in _ROLE_VOCAB if word in low]
    tokens.extend(match.group(0).lower() for match in _ASCII_TOKEN_RE.finditer(text))
    if not tokens:
        tokens.extend(segment.lower() for segment in _CJK_TOKEN_RE.findall(text))
    return _dedupe(tokens)


def _city_score(
    location: str, city: str, unknown_city: bool
) -> tuple[int, str, str]:
    if not str(city or "").strip():
        return 0, "", ""
    if unknown_city:
        return 0, "", "城市未知"
    normalized = _normalize_city(location)
    if any(hint in normalized for hint in _REMOTE_HINTS):
        return 20, "远程/全国岗位", ""
    if _normalize_city(city) in normalized:
        return 20, f"城市命中：{city}", ""
    return 0, "", f"城市不符：{location or '未知'}"


def _skill_score(job: JDEvidence, user_skills: list[str]) -> tuple[int, str, str]:
    if not user_skills:
        return 0, "", ""
    text = _job_text(job)
    matched = [skill for skill in user_skills if skill.lower() in text]
    unmatched = [skill for skill in user_skills if skill not in matched]
    score = round(20 * len(matched) / len(user_skills))
    reason = ""
    gap = ""
    if matched:
        reason = f"技能命中 {len(matched)}/{len(user_skills)}：{'、'.join(matched)}"
    if unmatched:
        gap = f"技能缺口：{'、'.join(unmatched)}"
    return score, reason, gap


def _education_score(
    job: JDEvidence, user_education: str
) -> tuple[int, str, str]:
    required = education.normalize_education_tag(_job_text(job))
    user = education.normalize_education_tag(user_education)
    if not required["explicit"]:
        return 10, "JD 未标注学历门槛", ""
    if not user["explicit"]:
        return 0, "", "JD 有学历要求，档案未填写学历"

    score = 0
    gaps: list[str] = []
    degree_ok = not required["degree"] or _rank_ge(
        user["degree"], required["degree"], _DEGREE_RANK
    )
    tier_ok = not required["tier"] or _rank_ge(
        user["tier"], required["tier"], _TIER_RANK
    )
    if degree_ok:
        score += 6
    else:
        gaps.append(f"学历层级不足：要求{required['degree']}，你是{user['degree'] or '未填'}")
    if tier_ok:
        score += 4
    else:
        gaps.append(f"院校层次不足：要求{required['tier']}，你是{user['tier'] or '未填'}")

    reason = ""
    if score:
        required_tag = required["tag"] or required["degree"] or required["tier"]
        user_tag = user["tag"] or user["degree"] or user["tier"]
        reason = f"学历匹配：{user_tag} vs 要求 {required_tag}"
    return score, reason, "；".join(gaps)


def _tier_score(tier: str, target: TargetSpec) -> tuple[int, str, str]:
    if tier and tier in target.target_tiers:
        return 10, f"目标档位：{tier}", ""
    if tier and tier in target.bridge_tiers:
        return 8, f"桥接档位：{tier}", ""
    return 3, "", f"非目标档位：{tier or '未知'}"


def _missing_demand_terms(job: JDEvidence, demand_terms: list[str], limit: int = 3) -> list[str]:
    text = _job_text(job)
    missing = [term for term in demand_terms if term.lower() not in text][:limit]
    return missing


def _demand_terms(requirement: RequirementProfile | None) -> list[str]:
    if requirement is None:
        return []
    terms: list[str] = []
    for items in (
        requirement.high_frequency,
        requirement.company_specific,
        requirement.nice_to_have,
        requirement.interview_topics,
    ):
        for item in items:
            term = str(item.term or "").strip()
            if term:
                terms.append(term)
    return _dedupe(terms)


def _job_text(job: JDEvidence) -> str:
    return " ".join(
        part
        for part in (job.title, job.summary, job.description, job.requirements)
        if part
    ).lower()


def _make_candidate(
    job: JDEvidence,
    order: int,
    score: int,
    reasons: list[str],
    gaps: list[str],
    status: str,
) -> ApplicationCandidate:
    return ApplicationCandidate(
        id=f"APP{order + 1:03d}",
        company=job.company or job.company_id,
        company_id=job.company_id,
        tier=job.tier,
        title=job.title,
        location=job.location,
        salary=job.salary,
        url=job.url,
        source=job.source,
        match_score=score,
        reasons=reasons,
        gaps=gaps,
        status="applied" if status == "applied" else "pending",
    )


def _dedupe_candidates(candidates: list[ApplicationCandidate]) -> list[ApplicationCandidate]:
    """URL 优先去重，无 URL 时用 company+title+location；保留已排序的第一条。"""
    seen: set[tuple[str, ...]] = set()
    result: list[ApplicationCandidate] = []
    for candidate in candidates:
        key = _candidate_key(candidate)
        if key in seen:
            continue
        seen.add(key)
        result.append(candidate)
    return result


def _candidate_key(candidate: ApplicationCandidate) -> tuple[str, ...]:
    url = str(candidate.url or "").strip().rstrip("/").lower()
    if url:
        return ("url", url)
    return (
        "title",
        _norm_text(candidate.company),
        _norm_text(candidate.title),
        _norm_text(candidate.location),
    )


def _city_keep(location: str, city: str) -> tuple[bool, bool]:
    """返回 (是否保留, 是否城市未知)。

    目标城市非空、location 为空时视为不匹配：keep=False, unknown=True
    （城市是硬筛，空 location 不能静默放行）；目标城市为空时保留所有岗位。
    """
    raw = str(location or "").strip()
    if not str(city or "").strip():
        return True, False
    if not raw:
        return False, True
    normalized = _normalize_city(raw)
    if any(hint in normalized for hint in _REMOTE_HINTS):
        return True, False
    return _normalize_city(city) in normalized, False


def _candidate_status(
    job: JDEvidence, applied_keys: set[tuple[str, str]]
) -> str:
    key = (_norm_text(job.company), _norm_text(job.title))
    return "applied" if key in applied_keys else "pending"


def _applied_keys(profile: Any) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for application in getattr(profile, "applications", []) or []:
        company = _norm_text(getattr(application, "company", ""))
        role = _norm_text(getattr(application, "role", ""))
        if company and role:
            keys.add((company, role))
    return keys


def _user_skills(profile: Any) -> list[str]:
    have = profile.have if isinstance(profile.have, dict) else {}
    raw = have.get("skills")
    items: list[str] = []
    if isinstance(raw, str):
        items = [part for part in _SKILL_SPLIT_RE.split(raw) if part.strip()]
    elif isinstance(raw, (list, tuple, set)):
        for item in raw:
            if isinstance(item, str):
                items.append(item)
            elif isinstance(item, dict):
                for key in ("name", "skill", "label"):
                    value = item.get(key)
                    if isinstance(value, str) and value.strip():
                        items.append(value)
                        break
    return _dedupe([item.strip() for item in items if item.strip()])


def _user_education(profile: Any) -> str:
    who = profile.who if isinstance(profile.who, dict) else {}
    parts = [
        str(who.get(key) or "").strip()
        for key in ("education", "education_tag", "degree", "tier")
    ]
    return " ".join(part for part in parts if part)


def _save_state(
    profile_name: str,
    profile: Any,
    candidates: list[ApplicationCandidate],
    *,
    evidence_run_id: str,
    requirement_profile_id: str,
    city: str,
    role: str,
    total_scored: int,
) -> str:
    store = ArtifactStore()
    meta = ArtifactMeta(
        id=store.new_id("as_"),
        stage=STAGE_APPLICATIONS,
        profile_name=profile_name,
        created_at=datetime.now().isoformat(),
        inputs={
            "evidence_run_id": evidence_run_id,
            "requirement_profile_id": requirement_profile_id,
            "city": city,
            "role": role,
        },
        validation={
            "candidate_count": len(candidates),
            "total_scored": total_scored,
        },
    )
    artifact = ApplicationState(
        meta=meta,
        evidence_run_id=evidence_run_id,
        applications=[application.model_dump() for application in profile.applications],
        funnel=funnel_stats(profile),
        candidates=candidates,
    )
    artifact_id = store.save(artifact)
    merge_core_state(profile_name, {KEY_APPLICATIONS: artifact_id}, advance_stage=False)
    return artifact_id


def mark_candidate_status(
    profile_name: str,
    company: str,
    role: str = "",
    status: str = "applied",
) -> bool:
    """把投递清单里对应候选标记为 applied/pending；没有清单或未命中返回 False。"""
    if status not in ("pending", "applied"):
        return False
    company_key = _norm_text(company)
    role_key = _norm_text(role)
    if not company_key:
        return False
    profile = load_profile(profile_name)
    state = profile.core_state if isinstance(profile.core_state, dict) else {}
    store = ArtifactStore()
    artifact_id = str(state.get(KEY_APPLICATIONS) or "")
    data = store.load(artifact_id) if artifact_id else None
    if not isinstance(data, dict):
        data = store.latest(profile_name, STAGE_APPLICATIONS)
    if not isinstance(data, dict):
        return False
    try:
        artifact = ApplicationState.model_validate(data)
    except Exception:  # noqa: BLE001 - 损坏清单不阻断投递登记
        return False

    changed = False
    for candidate in artifact.candidates:
        if _norm_text(candidate.company) != company_key:
            continue
        if role_key and role_key not in _norm_text(candidate.title):
            continue
        if candidate.status != status:
            candidate.status = status
            changed = True
    if not changed:
        return False

    artifact.meta.created_at = datetime.now().isoformat()
    store.save(artifact)
    merge_core_state(profile_name, {KEY_APPLICATIONS: artifact.meta.id}, advance_stage=False)
    return True


def _rank_ge(value: str, required: str, ranks: dict[str, int]) -> bool:
    return ranks.get(value, -1) >= ranks.get(required, 0)


def _normalize_city(text: Any) -> str:
    value = re.sub(r"\s+", "", str(text or "")).lower()
    return value[:-1] if value.endswith("市") else value


def _norm_text(text: Any) -> str:
    return re.sub(r"\s+", "", str(text or "")).lower()


def _as_str_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.lower()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


__all__ = ["DEFAULT_MIN_SCORE", "DEFAULT_TOP", "MissingEvidenceError", "run"]
