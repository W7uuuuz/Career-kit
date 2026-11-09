"""Core v2 artifact 模型——阶段之间唯一的数据契约。

字段与 `docs/internal/architecture-v2.md` 第 4 节一致；模型只描述结构，
抓取、统计、校验等确定性逻辑由阶段实现负责。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ArtifactMeta(BaseModel):
    """所有 artifact 共有的元信息。`id` 由 ArtifactStore.new_id 生成。"""

    id: str
    stage: str
    profile_name: str
    version: int = 1
    created_at: str
    inputs: dict[str, str] = Field(default_factory=dict)
    source_status: list[dict[str, Any]] = Field(default_factory=list)
    validation: dict[str, Any] = Field(default_factory=dict)


class TargetSpec(BaseModel):
    """目标岗位定位——阶段 6 的输入，从旧档案 want/who 适配。

    TargetSpec 本身不带 meta；持久化时由 `core.sync` 包装为带 `ArtifactMeta`
    的 `_TargetArtifact`，`meta.stage=target`，上游 `meta.inputs.profile_id`
    必须指向当前档案的 ProfileSnapshot。
    """

    direction: str = ""
    role: str = ""
    city: str = ""
    target_tiers: list[str] = Field(default_factory=list)
    bridge_tiers: list[str] = Field(default_factory=list)
    graduation_year: str = ""
    constraints: list[str] = Field(default_factory=list)


class ProfileSnapshot(BaseModel):
    """档案只读快照——阶段 9 校准执行方案时的输入。

    与 TargetSpec 一样不带 meta；持久化时由 `core.sync` 包装为带
    `ArtifactMeta` 的 `_ProfileArtifact`，`meta.stage=profile`。
    """

    name: str = ""
    who: dict[str, Any] = Field(default_factory=dict)
    have: dict[str, Any] = Field(default_factory=dict)
    want: dict[str, Any] = Field(default_factory=dict)
    gap: dict[str, Any] = Field(default_factory=dict)
    plan: dict[str, Any] = Field(default_factory=dict)
    summary: str = ""
    updated_at: str = ""


class CompanyEntry(BaseModel):
    """目标企业池中的单个企业。"""

    id: str
    name: str
    tier: str
    industry: str
    scrapable: bool
    scrapers: list[str] = Field(default_factory=list)
    careers_url: str = ""
    status: Literal["recommended", "confirmed", "excluded"] = "recommended"
    reason: str = ""


class CompanyPool(BaseModel):
    """阶段 6 产物：目标企业池。"""

    meta: ArtifactMeta
    target_spec: TargetSpec
    companies: list[CompanyEntry]
    counts: dict[str, int] = Field(default_factory=dict)
    gaps: list[str] = Field(default_factory=list)


class JDEvidence(BaseModel):
    """单条 JD 证据。"""

    id: str
    company_id: str
    company: str
    tier: str
    title: str
    location: str = ""
    salary: str = ""
    url: str = ""
    summary: str = ""
    description: str = ""
    requirements: str = ""
    source: str = ""
    fetched_at: str = ""
    detail_status: Literal["ok", "missing", "failed", "list_only"] = "missing"
    reused: bool = False


class InterviewEvidence(BaseModel):
    """单条面经证据；company_id 为空表示通用面经。"""

    id: str
    company_id: str = ""
    company: str = ""
    title: str = ""
    source: str = ""
    url: str = ""
    education_tag: str = ""
    year: str = ""
    highlights: list[str] = Field(default_factory=list)
    content: str = ""
    fetched_at: str = ""
    reused: bool = False


class EvidenceRun(BaseModel):
    """阶段 7 产物：一次采集的 JD 与面经证据集合。"""

    meta: ArtifactMeta
    target_spec: TargetSpec
    company_pool_id: str
    jd_items: list[JDEvidence] = Field(default_factory=list)
    interview_items: list[InterviewEvidence] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    confidence: dict[str, str] = Field(default_factory=dict)
    gaps: list[str] = Field(default_factory=list)
    report_paths: dict[str, str] = Field(default_factory=dict)


class RequirementItem(BaseModel):
    """需求条目——所有数字由代码统计，LLM 不得改写。"""

    term: str
    category: str
    jd_count: int
    jd_frequency: float
    company_count: int
    company_frequency: float
    companies: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    ci_low: float | None = None
    ci_high: float | None = None
    tier_breakdown: dict[str, int] = Field(default_factory=dict)


class HardRequirement(BaseModel):
    """单条 JD 的硬门槛（学历/经验），不聚合为全局结论。"""

    evidence_id: str
    company: str = ""
    title: str = ""
    education: str = ""
    experience: str = ""
    note: str = ""


class RequirementProfile(BaseModel):
    """阶段 8 产物：确定性统计 + LLM 定性解读。"""

    meta: ArtifactMeta
    evidence_run_id: str
    sample_size_jd: int = 0
    sample_size_interview: int = 0
    confidence_jd: str = "low"
    confidence_interview: str = "low"
    high_frequency: list[RequirementItem] = Field(default_factory=list)
    company_specific: list[RequirementItem] = Field(default_factory=list)
    interview_topics: list[RequirementItem] = Field(default_factory=list)
    hard_requirements: list[HardRequirement] = Field(default_factory=list)
    nice_to_have: list[RequirementItem] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    interpretation: dict[str, Any] = Field(default_factory=dict)


class PlanChange(BaseModel):
    """执行方案中的单条变更；必须引用 evidence_ids。"""

    type: Literal[
        "add_task",
        "modify_task",
        "remove_task",
        "reorder_tasks",
        "modify_phase",
        "add_phase",
        "remove_phase",
        "reorder_phases",
    ]
    phase_id: str = ""
    task_id: str = ""
    details: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    evidence_ids: list[str] = Field(default_factory=list)


class ExecutionPlan(BaseModel):
    """阶段 9 产物：执行版路线图与变更清单。"""

    meta: ArtifactMeta
    baseline_plan_id: str = ""
    requirement_profile_id: str = ""
    strategy_summary: str = ""
    roadmap: dict[str, Any] = Field(default_factory=dict)
    completed_evidence: list[dict[str, Any]] = Field(default_factory=list)
    changes: list[PlanChange] = Field(default_factory=list)
    diff_summary: str = ""
    applied: bool = False


class MarketBaseline(BaseModel):
    """阶段 3 产物：市场基线调研（岗位样本、案例与报告路径）。"""

    meta: ArtifactMeta
    target_spec: TargetSpec = Field(default_factory=TargetSpec)
    jd_samples: list[dict[str, Any]] = Field(default_factory=list)
    case_samples: list[dict[str, Any]] = Field(default_factory=list)
    digest: dict[str, Any] = Field(default_factory=dict)
    source_status: list[dict[str, Any]] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    gaps: list[str] = Field(default_factory=list)
    report_paths: dict[str, str] = Field(default_factory=dict)


class GapReport(BaseModel):
    """阶段 4 产物：能力差距诊断。"""

    meta: ArtifactMeta
    profile_snapshot_id: str = ""
    market_baseline_id: str = ""
    match_score: int = 0
    match_level: str = ""
    start_level: str = ""
    strengths: list[dict[str, Any]] = Field(default_factory=list)
    resume_red_flags: list[dict[str, Any]] = Field(default_factory=list)
    resume_optimization: dict[str, Any] = Field(default_factory=dict)
    interview_preparation: dict[str, Any] = Field(default_factory=dict)
    skill_gaps: list[dict[str, Any]] = Field(default_factory=list)
    priority_actions: list[dict[str, Any]] = Field(default_factory=list)
    market_context: str = ""


class BaselinePlan(BaseModel):
    """阶段 5 产物：基线培养方案。"""

    meta: ArtifactMeta
    gap_report_id: str = ""
    strategy_summary: str = ""
    roadmap: dict[str, Any] = Field(default_factory=dict)


class ExecutionState(BaseModel):
    """阶段 10 产物：任务执行与打卡状态。"""

    meta: ArtifactMeta
    execution_plan_id: str = ""
    current_phase_id: str = ""
    task_counts: dict[str, int] = Field(default_factory=dict)
    checkin_counts: dict[str, int] = Field(default_factory=dict)
    capability_evidence: list[dict[str, Any]] = Field(default_factory=list)


class ApplicationCandidate(BaseModel):
    """投递清单中的单个候选岗位（由证据池筛选与打分产生）。"""

    id: str
    company: str
    company_id: str = ""
    tier: str = ""
    title: str
    location: str = ""
    salary: str = ""
    url: str = ""
    source: str = ""
    match_score: int = 0
    reasons: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    status: Literal["pending", "applied"] = "pending"


class ApplicationState(BaseModel):
    """阶段 11 产物：求职投递与漏斗状态。

    - `applications` 保存用户口述的投递/面试记录；
    - `funnel` 保存按事件历史计算的漏斗统计；
    - `candidates` 保存 build_application_list 生成并落库的投递候选清单。
    """

    meta: ArtifactMeta
    evidence_run_id: str = ""
    applications: list[dict[str, Any]] = Field(default_factory=list)
    funnel: dict[str, Any] = Field(default_factory=dict)
    candidates: list[ApplicationCandidate] = Field(default_factory=list)


class ReviewReport(BaseModel):
    """阶段 12 产物：周期复盘与计划失配信号。"""

    meta: ArtifactMeta
    execution_state_id: str = ""
    plan_fit: dict[str, Any] = Field(default_factory=dict)
    weekly_facts: dict[str, Any] = Field(default_factory=dict)
    recommendations: list[str] = Field(default_factory=list)


__all__ = [
    "ApplicationCandidate",
    "ApplicationState",
    "ArtifactMeta",
    "BaselinePlan",
    "CompanyEntry",
    "CompanyPool",
    "EvidenceRun",
    "ExecutionPlan",
    "ExecutionState",
    "GapReport",
    "HardRequirement",
    "InterviewEvidence",
    "JDEvidence",
    "MarketBaseline",
    "PlanChange",
    "ProfileSnapshot",
    "RequirementItem",
    "RequirementProfile",
    "ReviewReport",
    "TargetSpec",
]
