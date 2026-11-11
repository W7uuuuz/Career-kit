"""用户资产目录（src/assets.py）的约束。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

import src.assets as assets


def test_sanitize_name_rules():
    """非法字符/超长/default 的归一。"""
    assert assets.sanitize_name(None) == assets.DEFAULT_SANITIZED
    assert assets.sanitize_name("") == assets.DEFAULT_SANITIZED
    assert assets.sanitize_name("default") == assets.DEFAULT_SANITIZED
    assert assets.sanitize_name("  ") == assets.DEFAULT_SANITIZED
    bad = 'a<b>c:d"e/f\\g|h?i*j'
    assert assets.sanitize_name(bad) == "a_b_c_d_e_f_g_h_i_j"
    assert assets.sanitize_name("CON") != "CON"  # Windows 保留名加后缀
    assert assets.sanitize_name("x" * 100) == "x" * 40  # 截断
    assert assets.sanitize_name(".hidden. ") == "hidden"  # 去除首尾空格


def test_get_assets_root_env_priority(monkeypatch, tmp_path):
    """CAREER_KIT_ASSETS_DIR 优先于 ~/CareerKit。"""
    monkeypatch.setenv("CAREER_KIT_ASSETS_DIR", str(tmp_path / "a"))
    assert assets.get_assets_root() == tmp_path / "a"
    monkeypatch.delenv("CAREER_KIT_ASSETS_DIR", raising=False)
    assert assets.get_assets_root() == Path.home() / "CareerKit"


def test_ensure_assets_root_creates_readme():
    """首次使用写说明.md，引导用户通过桌面快捷方式查看。"""
    root = assets.ensure_assets_root()
    readme = root / assets.README_FILENAME
    assert readme.exists()
    text = readme.read_text(encoding="utf-8-sig")
    assert "Career Kit" in text and "快捷方式" in text
    assert "index.html" not in text


def test_kind_assets_dir_layout(tmp_path, monkeypatch):
    """中文子目录：research / evidence / applications。"""
    monkeypatch.setenv("CAREER_KIT_ASSETS_DIR", str(tmp_path / "CareerKit"))
    d = assets.kind_assets_dir("research", "default")
    assert d == tmp_path / "CareerKit" / assets.DEFAULT_SANITIZED / "调研报告"
    d = assets.kind_assets_dir("evidence", "大厂冲刺")
    assert d == tmp_path / "CareerKit" / "大厂冲刺" / "证据池"
    try:
        assets.kind_assets_dir("roadmap", "default")
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("已删除的静态路线图资产类型不应再存在")


def test_next_asset_stem_and_write(tmp_path, monkeypatch):
    """文件名带日期与时分；写入资产目录。"""
    monkeypatch.setenv("CAREER_KIT_ASSETS_DIR", str(tmp_path / "CareerKit"))
    stem = assets.next_asset_stem("AI Agent")
    assert "AI_Agent" in stem.replace("-", "_") or "AI Agent" in stem
    assert len(stem) >= len("2000-01-01_")
    first = assets.write_asset_text("research", "默认档案", f"{stem}.md", "# 报告")
    assert first.exists()
    assert first.read_text(encoding="utf-8") == "# 报告"
