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
    """目标岗位定位——阶段 6 的输入，从旧档案 want/who 适配。"""

    direction: str = ""
    role: str = ""
    city: str = ""
    target_tiers: list[str] = Field(default_factory=list)
    bridge_tiers: list[str] = Field(default_factory=list)
    graduation_year: str = ""
    constraints: list[str] = Field(default_factory=list)


class ProfileSnapshot(BaseModel):
    """档案只读快照——阶段 9 校准执行方案时的输入。"""

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
    detail_status: Literal["ok", "missing", "failed"] = "missing"
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


__all__ = [
    "ArtifactMeta",
    "CompanyEntry",
    "CompanyPool",
    "EvidenceRun",
    "ExecutionPlan",
    "HardRequirement",
    "InterviewEvidence",
    "JDEvidence",
    "PlanChange",
    "ProfileSnapshot",
    "RequirementItem",
    "RequirementProfile",
    "TargetSpec",
]
