"""Artifact 模型与存储的统一出口。"""

from .models import (
    ArtifactMeta,
    CompanyEntry,
    CompanyPool,
    EvidenceRun,
    ExecutionPlan,
    HardRequirement,
    InterviewEvidence,
    JDEvidence,
    PlanChange,
    ProfileSnapshot,
    RequirementItem,
    RequirementProfile,
    TargetSpec,
)
from .store import ArtifactStore

__all__ = [
    "ArtifactMeta",
    "ArtifactStore",
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
