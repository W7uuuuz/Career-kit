"""SQLite 档案存储：JSON 仅作兼容镜像。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

import src.tools.profile as profile_module  # noqa: E402
from src.models import CareerProfile  # noqa: E402
from src.tools.profile import (
    delete_profile,
    list_profiles,
    load_profile,
    restore_profile,
    save_profile,
)


@pytest.fixture()
def temp_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(profile_module, "PROFILE_DIR", tmp_path)
    return tmp_path


def test_sqlite_is_source_of_truth(temp_profile):
    save_profile(CareerProfile(who={"name": "数据库"}))

    # 删除 JSON 镜像后仍能从 SQLite 读到
    (temp_profile / "default.json").unlink()
    assert load_profile().who["name"] == "数据库"


def test_json_only_profile_is_not_imported(temp_profile):
    json_only = {"who": {"name": "旧档案"}, "version": 3}
    (temp_profile / "orphan.json").write_text(
        json.dumps(json_only, ensure_ascii=False), encoding="utf-8"
    )

    profiles = list_profiles()
    assert all(p["name"] != "orphan" for p in profiles)
    assert load_profile("orphan").who == {}


def test_delete_and_restore_round_trip(temp_profile):
    save_profile(CareerProfile(who={"name": "回收站"}), name="trash_me")
    target = delete_profile("trash_me")
    assert target is not None
    assert all(p["name"] != "trash_me" for p in list_profiles())

    restore_profile("trash_me")
    assert load_profile("trash_me").who["name"] == "回收站"
