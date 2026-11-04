"""档案管理——初始化会话、逐步填充、确认档案、多档案切换。

多档案机制：
- 档案文件为 PROFILE_DIR/{name}.json，名称任意（默认 "default"）。
- 当前活跃档案记录在 PROFILE_DIR/.active_profile，无记录时回退 "default"。
- 不传 name 的所有读写操作都作用于当前活跃档案；
  显式传 name 的操作不受影响（测试/切换场景用）。

删除采用回收站式：delete_profile 把档案移入 PROFILE_DIR/trash/ 而非直接删除，
restore_profile 可从回收站恢复——用户数据是长期资产，删除必须可逆。
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from ..models import CareerProfile
from ..paths import PROFILE_DIR

ACTIVE_PROFILE_FILE = ".active_profile"

# 档案名白名单：防止路径穿越（"../x"、子目录、非法字符一律拒绝）
PROFILE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")

# 同一进程内可重入：MCP 工具和 Web 服务都可能在已持锁时调用 save_profile
_LOCK_STATE = threading.local()
# 初始化锁文件时避免多线程同时写首字节（Windows 上写入已锁区域会 PermissionError）
_LOCK_INIT = threading.Lock()


@contextmanager
def profile_lock(name: str | None = None) -> Iterator[None]:
    """跨进程档案写锁（Windows msvcrt / POSIX fcntl）。

    - 只保护「读-改-写」临界区，读操作依赖原子替换，不额外加锁。
    - 同一线程可重入，避免 save_profile 内部再次加锁死锁。
    """
    if name is None:
        name = get_active_profile_name()
    else:
        validate_profile_name(name)
    held: set[str] = getattr(_LOCK_STATE, "held", set())
    if name in held:
        yield
        return

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = PROFILE_DIR / f".{name}.lock"
    with _LOCK_INIT:
        if not lock_path.exists() or lock_path.stat().st_size == 0:
            with open(lock_path, "ab") as init:
                init.write(b"\0")
    with open(lock_path, "a+b") as handle:
        _acquire_lock(handle)
        held.add(name)
        _LOCK_STATE.held = held
        try:
            yield
        finally:
            held.discard(name)
            _release_lock(handle)


def _acquire_lock(handle: Any) -> None:
    if os.name == "nt":
        import msvcrt

        # 首字节由 _LOCK_INIT 预先写入；这里只锁，不读不写，避免已锁区域 PermissionError
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)


def _release_lock(handle: Any) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


_DB_READY: set[str] = set()


def _db_path() -> Path:
    return PROFILE_DIR / "career-kit.db"


def _connect() -> sqlite3.Connection:
    path = _db_path()
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS profiles ("
        "name TEXT PRIMARY KEY, data TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    key = str(path)
    if key not in _DB_READY:
        conn.execute("PRAGMA journal_mode=WAL")
        # 一次性导入已有 JSON 档案，兼容旧版本
        _import_json_profiles(conn)
        _DB_READY.add(key)
    return conn


def _import_json_profiles(conn: sqlite3.Connection) -> None:
    for json_path in PROFILE_DIR.glob("*.json"):
        try:
            data = json_path.read_text(encoding="utf-8")
            conn.execute(
                "INSERT OR IGNORE INTO profiles(name, data, updated_at) "
                "VALUES (?, ?, ?)",
                (json_path.stem, data, datetime.now().isoformat()),
            )
        except OSError:
            continue
    conn.commit()


def _read_profile_data(name: str) -> str | None:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT data FROM profiles WHERE name = ?", (name,)
        ).fetchone()
        return str(row["data"]) if row else None
    finally:
        conn.close()


def _write_profile_data(name: str, data: str) -> None:
    conn = _connect()
    try:
        with conn:
            conn.execute(
                "INSERT INTO profiles(name, data, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(name) DO UPDATE SET data=excluded.data, "
                "updated_at=excluded.updated_at",
                (name, data, datetime.now().isoformat()),
            )
    finally:
        conn.close()


def _delete_profile_data(name: str) -> None:
    conn = _connect()
    try:
        with conn:
            conn.execute("DELETE FROM profiles WHERE name = ?", (name,))
    finally:
        conn.close()


def validate_profile_name(name: str) -> str:
    """校验档案名，非法时抛 ValueError。"""
    if not name or not PROFILE_NAME_RE.match(name):
        raise ValueError(
            f"非法档案名「{name}」：只允许字母、数字、下划线、连字符"
        )
    return name


def get_active_profile_name() -> str:
    """读取当前活跃档案名，未设置或档案已不存在时回退 "default"。"""
    try:
        name = (PROFILE_DIR / ACTIVE_PROFILE_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        name = ""
    if not name:
        return "default"
    # 悬挂检测：active 指向的档案被删除后回退 default，避免读写落到空档案
    if not (PROFILE_DIR / f"{name}.json").exists():
        return "default"
    return name


def set_active_profile_name(name: str) -> None:
    """把指定档案设为当前活跃档案。"""
    validate_profile_name(name)
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    (PROFILE_DIR / ACTIVE_PROFILE_FILE).write_text(name, encoding="utf-8")


def profile_exists(name: str) -> bool:
    """档案是否存在（SQLite 为主，JSON 为兼容镜像）。非法档案名抛 ValueError。"""
    validate_profile_name(name)
    return (
        _read_profile_data(name) is not None
        or (PROFILE_DIR / f"{name}.json").exists()
    )


def list_profiles() -> list[dict[str, Any]]:
    """列出所有档案（SQLite 为主，JSON 为兼容镜像）。"""
    if not PROFILE_DIR.exists():
        return []
    active = get_active_profile_name()
    conn = _connect()
    try:
        _import_json_profiles(conn)
        rows = conn.execute(
            "SELECT name, data, updated_at FROM profiles ORDER BY name"
        ).fetchall()
    finally:
        conn.close()

    profiles = []
    for row in rows:
        name = str(row["name"])
        info: dict[str, Any] = {"name": name, "is_active": name == active}
        try:
            profile = CareerProfile.model_validate_json(str(row["data"]))
            info["version"] = profile.version
            info["updated_at"] = profile.updated_at
            who = profile.who or {}
            info["person"] = who.get("name") or who.get("raw", "")
            want = profile.want or {}
            info["target"] = (
                want.get("target_role") or want.get("direction") or want.get("raw", "")
            )
            info["has_plan"] = bool(
                profile.plan.get("roadmap") or profile.plan.get("phases")
            )
        except Exception:
            info["version"] = 0
            info["updated_at"] = str(row["updated_at"])
        profiles.append(info)
    return profiles


# === 回收站式删除 ===


def _trash_dir() -> Path:
    return PROFILE_DIR / "trash"


def delete_profile(name: str) -> Path | None:
    """把档案移入回收站（可恢复）。返回回收站文件路径，档案不存在返回 None。

    非法档案名抛 ValueError。注意：回收站式删除是安全操作，允许删除当前
    活跃档案——get_active_profile_name 会自动回退到 default。
    """
    validate_profile_name(name)
    path = PROFILE_DIR / f"{name}.json"
    data = _read_profile_data(name)
    if data is None and not path.exists():
        return None
    if not path.exists() and data is not None:
        path.write_text(data, encoding="utf-8")

    trash_dir = _trash_dir()
    trash_dir.mkdir(parents=True, exist_ok=True)

    # 同名档案多次删除：加时间戳区分，保留所有历史
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = trash_dir / f"{name}.json"
    with profile_lock(name):
        if target.exists():
            target = trash_dir / f"{name}_{ts}.json"
        path.rename(target)
        _delete_profile_data(name)
    return target


def list_trash() -> list[dict[str, Any]]:
    """列出回收站里的档案（可恢复项）。"""
    trash_dir = _trash_dir()
    if not trash_dir.exists():
        return []
    items = []
    for path in sorted(trash_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        items.append({
            "file": path.name,
            "profile_name": _trash_base_name(path.name),
            "deleted_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
        })
    return items


def _trash_base_name(filename: str) -> str:
    """从回收站文件名还原档案名：alice.json → alice；alice_20260828_120000.json → alice。"""
    return filename.split("_", 1)[0] if "_" in filename else Path(filename).stem


def restore_profile(name: str) -> Path | None:
    """从回收站恢复最新一份档案。回收站无此档案返回 None。

    目标位置已存在同名档案时抛 ValueError（拒绝覆盖新数据，防误恢复）。
    """
    validate_profile_name(name)
    target = PROFILE_DIR / f"{name}.json"
    if target.exists():
        raise ValueError(f"档案「{name}」已存在，拒绝覆盖——如需恢复请先处理现有档案")

    trash_dir = _trash_dir()
    if not trash_dir.exists():
        return None

    candidates = list(trash_dir.glob(f"{name}*.json"))
    if not candidates:
        return None
    # 取最新一份（mtime 最大）
    latest = max(candidates, key=lambda p: p.stat().st_mtime)
    with profile_lock(name):
        latest.rename(target)
        _write_profile_data(name, target.read_text(encoding="utf-8"))
    return target


def load_profile(name: str | None = None) -> CareerProfile:
    """从本地加载档案，不存在则返回空档案。

    name 为 None 时加载当前活跃档案（未设置则回退 "default"）。
    """
    if name is None:
        name = get_active_profile_name()
    else:
        validate_profile_name(name)
    data = _read_profile_data(name)
    if data is not None:
        return CareerProfile.model_validate_json(data)
    path = PROFILE_DIR / f"{name}.json"
    if path.exists():
        text = path.read_text(encoding="utf-8")
        _write_profile_data(name, text)
        return CareerProfile.model_validate_json(text)
    return CareerProfile()


def save_profile(profile: CareerProfile, name: str | None = None) -> None:
    """保存档案到本地（原子替换）。

    先写临时文件再 os.replace，避免 MCP 与 Web 同时读写时读到半截 JSON；
    写锁保证同一时刻只有一个写入方。
    """
    if name is None:
        name = get_active_profile_name()
    else:
        validate_profile_name(name)
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    path = PROFILE_DIR / f"{name}.json"
    data = profile.model_dump_json(indent=2)
    with profile_lock(name):
        _write_profile_data(name, data)
        # JSON 镜像：兼容 E2E harness、用户手工查看与旧版本回滚
        temp = path.with_name(f".{path.name}.tmp")
        temp.write_text(data, encoding="utf-8")
        os.replace(temp, path)


def merge_section(
    section: str, data: str, name: str | None = None
) -> CareerProfile:
    """将 data 合并到档案的指定 section 并保存。

    data 尝试按 JSON 解析；如果不是合法 JSON，则存为 {"raw": data}。

    Args:
        section: 目标 section（who/have/want/gap/plan）。
        data: LLM 传来的字符串，期望是 JSON。
        name: 档案名称；None 表示当前活跃档案（默认 "default"）。

    Returns:
        更新后的档案。
    """
    with profile_lock(name):
        profile = load_profile(name)

        try:
            parsed: dict[str, Any] = json.loads(data)
            if not isinstance(parsed, dict):
                parsed = {"raw": data}
        except (json.JSONDecodeError, TypeError):
            parsed = {"raw": data}

        profile.merge(section, parsed)
        save_profile(profile, name)
        return profile


def save_plan_snapshot(
    source: str, import_file: str | None = None, name: str | None = None
) -> CareerProfile:
    """保存当前 plan 到版本历史。

    Args:
        source: 来源标识（"generated" | "imported" | "manual"）
        import_file: 如果是导入的，记录文件路径
        name: 档案名称；None 表示当前活跃档案（默认 "default"）

    Returns:
        更新后的档案。
    """
    with profile_lock(name):
        profile = load_profile(name)
        profile.save_plan_snapshot(source, import_file)
        save_profile(profile, name)
        return profile
