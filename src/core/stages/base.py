"""阶段协议——每个阶段只承担一个决策或产物，阶段之间只通过 artifact 传递。"""

from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field


class StageContext(BaseModel):
    """阶段运行时上下文：档案名、artifact 存储与用户确认状态。"""

    profile_name: str
    store: Any
    user_confirmed: bool = False


class StageResult(BaseModel):
    """阶段执行结果；工具层据此决定是否请求用户确认或补充输入。"""

    status: Literal["ok", "needs_confirmation", "insufficient_data", "failed"]
    artifact_id: str = ""
    message: str = ""
    next_stage: str = ""
    questions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class Stage(Protocol):
    """阶段实现协议：模块级常量 + run/validate。"""

    STAGE_ID: str
    REQUIRES: tuple[str, ...]
    PRODUCES: str

    def run(self, ctx: StageContext, inputs: dict[str, Any]) -> StageResult: ...

    def validate(self, artifact: BaseModel) -> list[str]: ...


def clean_evidence_ids(raw: Any) -> list[str]:
    """把任意输入归一为去空后的 evidence id 列表。

    所有阶段共用这一个入口，避免「校验只查非空」「save 查未知」两套规则。
    """
    if not isinstance(raw, (list, tuple, set)):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def unknown_evidence_ids(evidence_ids: list[str], known: set[str]) -> list[str]:
    """返回不在已知证据集合中的 id；空列表表示全部有效。"""
    return sorted({item for item in evidence_ids if item not in known})


def evidence_id_problems(raw: Any, known: set[str] | None = None) -> list[str]:
    """统一的 evidence_ids 校验：空 id 必拒绝；给定 known 时未知 id 也拒绝。"""
    ids = clean_evidence_ids(raw)
    if not ids:
        return ["evidence_ids 不能为空"]
    if known is None:
        return []
    unknown = unknown_evidence_ids(ids, known)
    if unknown:
        return [f"未知 evidence_ids：{', '.join(unknown)}"]
    return []


__all__ = [
    "Stage",
    "StageContext",
    "StageResult",
    "clean_evidence_ids",
    "evidence_id_problems",
    "unknown_evidence_ids",
]
