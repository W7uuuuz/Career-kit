"""大对象草稿工具：分片写入，避免长 JSON 参数被传输层截断。"""

from __future__ import annotations

from ..mcp_app import mcp
from .draft_store import DraftError, append, clear, create, status
from .errors import error_response
from .tool_helpers import _json


@mcp.tool()
def draft_create(kind: str = "generic") -> str:
    """创建草稿，用于分片提交长分析结果。

    何时调用：内容预计超过 3-4KB（差距分析、路线图、执行方案）时，先创建草稿，
    再用 draft_append 分多次写入小片，最后把 draft_id 传给 save_* 工具。
    """
    try:
        return _json(create(kind))
    except DraftError as exc:
        return error_response(exc.code, exc.message)


@mcp.tool()
def draft_append(draft_id: str, chunk: str) -> str:
    """向草稿追加一段内容。chunk 建议不超过 2KB，按 JSON 结构分段。"""
    try:
        return _json(append(draft_id, chunk))
    except DraftError as exc:
        return error_response(exc.code, exc.message)


@mcp.tool()
def draft_status(draft_id: str) -> str:
    """查看草稿当前大小、片段数与 JSON 是否已闭合。"""
    try:
        return _json(status(draft_id))
    except DraftError as exc:
        return error_response(exc.code, exc.message)


@mcp.tool()
def draft_clear(draft_id: str) -> str:
    """删除草稿（保存成功后自动清理，失败或放弃时手动清理）。"""
    try:
        clear(draft_id)
        return _json({"draft_id": draft_id, "deleted": True})
    except DraftError as exc:
        return error_response(exc.code, exc.message)
