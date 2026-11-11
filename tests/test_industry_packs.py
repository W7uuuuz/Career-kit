"""行业包结构与命名空间回归。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

_REQUIRED_ROLE_FIELDS = (
    "name",
    "summary",
    "day_to_day",
    "entry",
    "skills",
    "growth",
    "fit_signals",
    "dealbreakers",
    "keywords",
)


def test_industry_packs_have_required_fields():
    from src.industries.loader import _load_all

    packs = _load_all()
    assert {
        "internet", "energy", "electronics", "mechanical", "electrical", "finance"
    } <= set(packs)
    for pid, pack in packs.items():
        assert pack.get("name"), pid
        assert pack.get("aliases"), pid
        assert (pack.get("related_majors") or {}).get("core"), pid
        assert pack.get("subdirections"), pid
        roles = pack.get("roles") or []
        assert roles, pid
        role_ids = [str(role.get("id", "")) for role in roles]
        assert all(role_ids), f"{pid} 存在缺少 id 的岗位"
        assert len(role_ids) == len(set(role_ids)), f"{pid} 岗位 id 重复"
        for role in roles:
            for key in _REQUIRED_ROLE_FIELDS:
                assert role.get(key), f"{pid}/{role.get('id')} 缺少 {key}"


def test_industry_aliases_unique():
    from src.industries.loader import _load_all

    seen: dict[str, str] = {}
    for pid, pack in _load_all().items():
        for alias in pack.get("aliases") or []:
            key = str(alias).strip().lower()
            assert key not in seen, f"别名 {alias} 同时属于 {seen.get(key)} 和 {pid}"
            seen[key] = pid


def test_loader_rejects_duplicate_alias(tmp_path, monkeypatch):
    import src.industries.loader as loader

    (tmp_path / "a.yaml").write_text("id: a\nname: A\naliases: [共享]\n", encoding="utf-8")
    (tmp_path / "b.yaml").write_text("id: b\nname: B\naliases: [共享]\n", encoding="utf-8")
    monkeypatch.setattr(loader, "INDUSTRIES_DIR", tmp_path)
    loader.clear_cache()
    try:
        with pytest.raises(loader.IndustryError):
            loader._load_all()
    finally:
        loader.clear_cache()
