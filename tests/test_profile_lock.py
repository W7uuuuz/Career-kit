"""档案写入安全：可重入锁与原子替换。"""

from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

import src.tools.profile as profile_module  # noqa: E402
from src.models import CareerProfile  # noqa: E402
from src.tools.profile import load_profile, profile_lock, save_profile  # noqa: E402


@pytest.fixture()
def temp_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(profile_module, "PROFILE_DIR", tmp_path)
    return tmp_path


def test_profile_lock_is_reentrant(temp_profile):
    profile = CareerProfile(who={"name": "张三"})
    with profile_lock():
        with profile_lock():
            save_profile(profile)

    assert load_profile().who["name"] == "张三"


def test_save_profile_is_atomic(temp_profile):
    profile = CareerProfile(who={"name": "原子"})
    save_profile(profile)

    path = temp_profile / "default.json"
    assert json.loads(path.read_text(encoding="utf-8"))["who"]["name"] == "原子"
    assert not list(temp_profile.glob("*.tmp"))


def test_concurrent_writes_leave_valid_json(temp_profile):
    def worker(index: int) -> None:
        with profile_lock():
            profile = load_profile()
            profile.who = {"name": f"用户{index}"}
            profile.touch()
            save_profile(profile)

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(worker, range(12)))

    final = load_profile()
    assert final.who["name"].startswith("用户")
    assert final.version >= 1
