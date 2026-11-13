"""大对象草稿存储：分片写入，绕开单参数体积上限。

长分析结果（差距分析、路线图）不再靠一个巨型 JSON 字符串传输；
模型先创建草稿，再分多次追加小片，最后由 save_* 工具按 draft_id 读取。
"""

from __future__ import annotations

import contextlib
import json
import re
import secrets
import time
from pathlib import Path

from . import profile as profile_store

DRAFT_ID_PREFIX = "dr_"
DRAFT_TTL_SECONDS = 24 * 60 * 60
DRAFT_MAX_BYTES = 2 * 1024 * 1024
_DRAFT_ID_RE = re.compile(r"^dr_[0-9a-f]{12}$")


class DraftError(Exception):
    """草稿操作失败（id 非法、过期、超限）。"""

    def __init__(self, message: str, code: str = "DRAFT_ERROR") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


def _draft_dir() -> Path:
    path = Path(profile_store.PROFILE_DIR) / "cache" / "drafts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _draft_path(draft_id: str) -> Path:
    if not _DRAFT_ID_RE.match(str(draft_id or "")):
        raise DraftError(f"草稿 id 非法：{draft_id!r}", code="INVALID_DRAFT_ID")
    return _draft_dir() / f"{draft_id}.json"


def create(kind: str = "generic") -> dict:
    draft_id = f"{DRAFT_ID_PREFIX}{secrets.token_hex(6)}"
    payload = {
        "id": draft_id,
        "kind": str(kind or "generic")[:40],
        "created_at": time.time(),
        "chunks": [],
    }
    _write(draft_id, payload)
    return {"draft_id": draft_id, "kind": payload["kind"], "bytes": 0}


def append(draft_id: str, chunk: str) -> dict:
    payload = _read(draft_id)
    text = str(chunk or "")
    if not text:
        raise DraftError("chunk 不能为空", code="INVALID_PARAM")
    payload["chunks"].append(text)
    size = len("".join(payload["chunks"]).encode("utf-8"))
    if size > DRAFT_MAX_BYTES:
        raise DraftError(
            f"草稿超过上限 {DRAFT_MAX_BYTES} 字节，请精简内容或分段保存",
            code="DRAFT_TOO_LARGE",
        )
    _write(draft_id, payload)
    return {"draft_id": draft_id, "bytes": size, "chunks": len(payload["chunks"])}


def status(draft_id: str) -> dict:
    payload = _read(draft_id)
    text = "".join(payload.get("chunks") or [])
    return {
        "draft_id": draft_id,
        "kind": payload.get("kind") or "",
        "bytes": len(text.encode("utf-8")),
        "chunks": len(payload.get("chunks") or []),
        "complete_hint": _complete_hint(text),
    }


def read_text(draft_id: str) -> str:
    payload = _read(draft_id)
    return "".join(payload.get("chunks") or [])


def clear(draft_id: str) -> None:
    with contextlib.suppress(OSError):
        _draft_path(draft_id).unlink(missing_ok=True)


def _read(draft_id: str) -> dict:
    path = _draft_path(draft_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise DraftError(f"草稿不存在或已过期：{draft_id}", code="DRAFT_NOT_FOUND") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise DraftError(f"草稿读取失败：{draft_id}", code="DRAFT_READ_FAILED") from exc
    if not isinstance(payload, dict):
        raise DraftError(f"草稿格式损坏：{draft_id}", code="DRAFT_READ_FAILED")
    if time.time() - float(payload.get("created_at") or 0) > DRAFT_TTL_SECONDS:
        path.unlink(missing_ok=True)
        raise DraftError(f"草稿已过期：{draft_id}", code="DRAFT_NOT_FOUND")
    return payload


def _write(draft_id: str, payload: dict) -> None:
    path = _draft_path(draft_id)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _complete_hint(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return "empty"
    if stripped.count("{") > stripped.count("}"):
        return "incomplete_json"
    return "balanced_or_non_json"
