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


__all__ = ["Stage", "StageContext", "StageResult"]
