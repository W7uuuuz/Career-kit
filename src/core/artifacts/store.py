"""Artifact 持久化——与档案同库的 SQLite 表。

每次操作使用独立连接（WAL + busy_timeout + 繁忙重试），阶段可并发保存互不阻塞。
`save` 接受任意带 `meta` 的 Pydantic 模型：版本号在 `BEGIN IMMEDIATE` 事务内分配，
保证同一 profile+stage 下并发保存得到唯一且递增的 version。

注意：`save` 只把 `meta.version` / `meta.created_at` 写入数据库，不会回填到调用方
对象（避免意外修改调用方模型）。调用方需要最新版本号时，请从返回值 `load(id)` 读取。
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
import time
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ... import paths

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS artifacts (
  id TEXT PRIMARY KEY,
  profile_name TEXT NOT NULL,
  stage TEXT NOT NULL,
  kind TEXT NOT NULL,
  version INTEGER NOT NULL,
  data TEXT NOT NULL,
  inputs TEXT NOT NULL,
  created_at TEXT NOT NULL,
  content_hash TEXT
)
"""

_CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_artifacts_profile_stage
  ON artifacts(profile_name, stage, created_at)
"""

_CREATE_VERSION_INDEX = """
CREATE INDEX IF NOT EXISTS idx_artifacts_profile_stage_version
  ON artifacts(profile_name, stage, version, created_at)
"""

_ID_LOCK = threading.Lock()
_ISSUED_IDS: set[str] = set()

_BUSY_RETRIES = 6
_BUSY_INITIAL_DELAY = 0.05


def _is_busy_error(exc: BaseException) -> bool:
    """判断 SQLite 错误是否属于可重试的锁竞争。"""
    if not isinstance(exc, sqlite3.OperationalError):
        return False
    text = str(exc).lower()
    return "locked" in text or "busy" in text


def _retry_on_busy(func: Any) -> Any:
    """在 SQLite 锁竞争时指数退避重试。"""
    delay = _BUSY_INITIAL_DELAY
    for attempt in range(_BUSY_RETRIES):
        try:
            return func()
        except sqlite3.OperationalError as exc:
            if not _is_busy_error(exc) or attempt == _BUSY_RETRIES - 1:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 1.0)
    raise AssertionError("unreachable")


class ArtifactStore:
    """Artifact 存取层；`db_path` 为空时使用 `paths.PROFILE_DIR/career-kit.db`。"""

    # 每个 profile+stage 保留的版本上限；测试可 monkeypatch。
    MAX_PER_STAGE = 100

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._db_path = Path(db_path) if db_path is not None else None

    @property
    def db_path(self) -> Path:
        """当前使用的数据库文件路径（构造后仍会跟随 PROFILE_DIR 变化）。"""
        if self._db_path is not None:
            return self._db_path
        return paths.PROFILE_DIR / "career-kit.db"

    def save(self, artifact: BaseModel, dedupe: bool = False) -> str:
        """保存 artifact 并返回 id；同一阶段的新 artifact 自动递增版本号。

        版本号在 `BEGIN IMMEDIATE` 事务内分配，并发保存同一 profile+stage 时
        由 SQLite 写锁串行化，不会得到重复 version。`meta.created_at` /
        `meta.version` 只落库，不回填调用方对象。

        ``dedupe=True`` 时，若同一 profile+stage 已存在内容完全相同的 artifact
        （``content_hash`` 排除 meta.id/version/created_at），直接复用其 id，
        不新增行也不递增版本。同一 id 重复保存且内容不变时同样不写库；内容变化
        则 version +1。
        """
        if not isinstance(artifact, BaseModel):
            raise TypeError("ArtifactStore.save 只接受 Pydantic 模型")
        meta = getattr(artifact, "meta", None)
        if meta is None:
            raise ValueError("artifact 缺少 meta 字段")
        artifact_id = str(getattr(meta, "id", "") or "")
        profile_name = str(getattr(meta, "profile_name", "") or "")
        stage = str(getattr(meta, "stage", "") or "")
        if not artifact_id or not profile_name or not stage:
            raise ValueError("artifact meta 缺少 id/profile_name/stage")

        requested_version = max(int(getattr(meta, "version", 1) or 1), 1)
        created_at = str(getattr(meta, "created_at", "") or "") or datetime.now().isoformat()
        inputs = json.dumps(getattr(meta, "inputs", {}) or {}, ensure_ascii=False)
        kind = type(artifact).__name__
        content_hash = _content_hash(artifact.model_dump(mode="json"))

        def write() -> str:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    existing = conn.execute(
                        "SELECT version, content_hash FROM artifacts WHERE id = ?",
                        (artifact_id,),
                    ).fetchone()
                    if dedupe:
                        match = conn.execute(
                            "SELECT id FROM artifacts WHERE profile_name = ? AND stage = ? "
                            "AND content_hash = ? "
                            "ORDER BY version DESC, created_at DESC, rowid DESC LIMIT 1",
                            (profile_name, stage, content_hash),
                        ).fetchone()
                        if match is not None:
                            conn.execute("COMMIT")
                            return str(match["id"])
                    if existing is not None and str(existing["content_hash"] or "") == content_hash:
                        conn.execute("COMMIT")
                        return artifact_id

                    if existing is not None:
                        version = max(int(existing["version"]) + 1, requested_version)
                    else:
                        version = self._next_version(
                            conn, artifact_id, profile_name, stage, requested_version
                        )
                    stored_meta = meta.model_copy(
                        update={"version": version, "created_at": created_at}
                    )
                    payload = artifact.model_copy(
                        update={"meta": stored_meta}
                    ).model_dump_json()
                    conn.execute(
                        "INSERT INTO artifacts"
                        "(id, profile_name, stage, kind, version, data, inputs, created_at, "
                        "content_hash) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                        "ON CONFLICT(id) DO UPDATE SET profile_name=excluded.profile_name, "
                        "stage=excluded.stage, kind=excluded.kind, version=excluded.version, "
                        "data=excluded.data, inputs=excluded.inputs, created_at=excluded.created_at, "
                        "content_hash=excluded.content_hash",
                        (
                            artifact_id,
                            profile_name,
                            stage,
                            kind,
                            version,
                            payload,
                            inputs,
                            created_at,
                            content_hash,
                        ),
                    )
                    self._prune(conn, profile_name, stage)
                    conn.execute("COMMIT")
                    return artifact_id
                except BaseException:
                    with suppress(sqlite3.Error):
                        conn.execute("ROLLBACK")
                    raise
            finally:
                conn.close()

        return _retry_on_busy(write)

    def _prune(self, conn: sqlite3.Connection, profile_name: str, stage: str) -> None:
        """保留该 profile+stage 最新的 N 个版本，删除更旧的版本。"""
        limit = int(getattr(self, "MAX_PER_STAGE", 100) or 0)
        if limit <= 0:
            return
        rows = conn.execute(
            "SELECT id FROM artifacts WHERE profile_name = ? AND stage = ? "
            "ORDER BY version DESC, created_at DESC, rowid DESC LIMIT -1 OFFSET ?",
            (profile_name, stage, limit),
        ).fetchall()
        if not rows:
            return
        ids = [str(row["id"]) for row in rows]
        placeholders = ",".join("?" for _ in ids)
        conn.execute(f"DELETE FROM artifacts WHERE id IN ({placeholders})", ids)

    def _next_version(
        self,
        conn: sqlite3.Connection,
        artifact_id: str,
        profile_name: str,
        stage: str,
        requested_version: int,
    ) -> int:
        """在已持有写锁的事务内分配版本号（调用方必须已 BEGIN IMMEDIATE）。"""
        row = conn.execute(
            "SELECT version FROM artifacts WHERE id = ?", (artifact_id,)
        ).fetchone()
        if row is not None:
            return max(requested_version, int(row["version"]))
        max_row = conn.execute(
            "SELECT MAX(version) AS version FROM artifacts "
            "WHERE profile_name = ? AND stage = ?",
            (profile_name, stage),
        ).fetchone()
        max_version = int(max_row["version"] or 0) if max_row else 0
        return max(max_version + 1, requested_version)

    def load(self, artifact_id: str) -> dict[str, Any] | None:
        """按 id 读取 artifact；不存在或数据损坏时返回 None。"""
        if not artifact_id:
            return None
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT data FROM artifacts WHERE id = ?", (artifact_id,)
            ).fetchone()
        finally:
            conn.close()
        return _decode(row["data"]) if row is not None else None

    def latest(self, profile_name: str, stage: str) -> dict[str, Any] | None:
        """读取指定档案与阶段的最新 artifact（version 优先，created_at 兜底）。"""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT data FROM artifacts WHERE profile_name = ? AND stage = ? "
                "ORDER BY version DESC, created_at DESC, rowid DESC LIMIT 1",
                (profile_name, stage),
            ).fetchone()
        finally:
            conn.close()
        return _decode(row["data"]) if row is not None else None

    def list(self, profile_name: str, stage: str = "") -> list[dict[str, Any]]:
        """按版本倒序列出 artifact；stage 为空时返回所有阶段。"""
        sql = "SELECT data FROM artifacts WHERE profile_name = ?"
        params: list[Any] = [profile_name]
        if stage:
            sql += " AND stage = ?"
            params.append(stage)
        sql += " ORDER BY version DESC, created_at DESC, rowid DESC"
        conn = self._connect()
        try:
            rows = conn.execute(sql, params).fetchall()
        finally:
            conn.close()
        items: list[dict[str, Any]] = []
        for row in rows:
            data = _decode(row["data"])
            if data is not None:
                items.append(data)
        return items

    def new_id(self, prefix: str) -> str:
        """生成 `{prefix}_{YYYYMMDD_HHMMSS}_{6位hex}` 形式的唯一 id。"""
        clean = prefix.strip().rstrip("_")
        if not clean:
            raise ValueError("artifact id 前缀不能为空")
        while True:
            candidate = f"{clean}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(3)}"
            with _ID_LOCK:
                if candidate not in _ISSUED_IDS:
                    _ISSUED_IDS.add(candidate)
                    return candidate

    def _connect(self) -> sqlite3.Connection:
        def open_connection() -> sqlite3.Connection:
            db_path = self.db_path
            db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(db_path, timeout=30.0, isolation_level=None)
            try:
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA busy_timeout=30000")
                conn.execute("PRAGMA journal_mode=WAL")
                _ensure_schema(conn)
            except BaseException:
                conn.close()
                raise
            return conn

        return _retry_on_busy(open_connection)


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """建表并兼容旧库：补 content_hash 列并回填历史行。"""
    conn.execute(_CREATE_TABLE)
    conn.execute(_CREATE_INDEX)
    conn.execute(_CREATE_VERSION_INDEX)
    columns = {
        str(row["name"]) for row in conn.execute("PRAGMA table_info(artifacts)").fetchall()
    }
    if "content_hash" not in columns:
        try:
            conn.execute("ALTER TABLE artifacts ADD COLUMN content_hash TEXT")
        except sqlite3.OperationalError as exc:
            if "duplicate column" not in str(exc).lower():
                raise
    rows = conn.execute(
        "SELECT id, data FROM artifacts WHERE content_hash IS NULL"
    ).fetchall()
    for row in rows:
        data = _decode(row["data"])
        if data is None:
            continue
        conn.execute(
            "UPDATE artifacts SET content_hash = ? WHERE id = ?",
            (_content_hash(data), row["id"]),
        )


def _content_hash(data: dict[str, Any]) -> str:
    """计算内容哈希；排除 meta.id/version/created_at，避免无意义的新版本。"""
    try:
        payload = json.loads(json.dumps(data, ensure_ascii=False, sort_keys=True))
    except (TypeError, ValueError):
        payload = dict(data)
    meta = payload.get("meta")
    if isinstance(meta, dict):
        for key in ("id", "version", "created_at"):
            meta.pop(key, None)
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _decode(raw: Any) -> dict[str, Any] | None:
    try:
        data = json.loads(str(raw))
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None
