"""用户资产目录（src/assets.py）契约测试。

用户资产与程序数据彻底分离：环境变量优先、中文子目录、固定名 vs 日期留档、
index.html 总入口幂等重建、说明.md 首建。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

import src.assets as assets


def test_sanitize_name_rules():
    """非法字符/保留名/空与 default 的归一。"""
    assert assets.sanitize_name(None) == assets.DEFAULT_SANITIZED
    assert assets.sanitize_name("") == assets.DEFAULT_SANITIZED
    assert assets.sanitize_name("default") == assets.DEFAULT_SANITIZED
    assert assets.sanitize_name("  ") == assets.DEFAULT_SANITIZED
    bad = 'a<b>c:d"e/f\\g|h?i*j'
    assert assets.sanitize_name(bad) == "a_b_c_d_e_f_g_h_i_j"
    assert assets.sanitize_name("CON") != "CON"  # Windows 保留名加后缀
    assert assets.sanitize_name("x" * 100) == "x" * 40  # 截断
    assert assets.sanitize_name(".hidden. ") == "hidden"  # 去首尾点空白


def test_get_assets_root_env_priority(monkeypatch, tmp_path):
    """CAREER_KIT_ASSETS_DIR 优先于 ~/CareerKit。"""
    monkeypatch.setenv("CAREER_KIT_ASSETS_DIR", str(tmp_path / "a"))
    assert assets.get_assets_root() == tmp_path / "a"
    monkeypatch.delenv("CAREER_KIT_ASSETS_DIR", raising=False)
    assert assets.get_assets_root() == Path.home() / "CareerKit"


def test_ensure_assets_root_creates_readme(tmp_path):
    """首次使用生成 说明.md（用户打开文件夹能看到这是什么）。"""
    root = assets.ensure_assets_root()
    try:
        assert root.exists()
        readme = root / assets.README_FILENAME
        assert readme.exists()
        text = readme.read_text(encoding="utf-8")
        assert "index.html" in text and "调研报告" in text
        import os

        monkeypatch_env = os.environ.get("CAREER_KIT_ASSETS_DIR")
        assert monkeypatch_env, "说明.md 应写在测试沙箱资产根"
    finally:
        import shutil

        shutil.rmtree(root, ignore_errors=True)


def test_kind_assets_dir_layout(tmp_path, monkeypatch):
    """四类产出落各自中文子目录；档案名 default → 默认档案。"""
    monkeypatch.setenv("CAREER_KIT_ASSETS_DIR", str(tmp_path / "CareerKit"))
    d = assets.kind_assets_dir("research", "default")
    assert d == tmp_path / "CareerKit" / assets.DEFAULT_SANITIZED / "调研报告"
    d = assets.kind_assets_dir("roadmap", "大厂冲刺")
    assert d == tmp_path / "CareerKit" / "大厂冲刺" / "路线图"


def test_fixed_vs_dated_filenames(tmp_path, monkeypatch):
    """路线图/仪表盘固定名（保 localStorage），调研/差距带日期留档。"""
    monkeypatch.setenv("CAREER_KIT_ASSETS_DIR", str(tmp_path / "CareerKit"))
    assert assets.ASSETS_FILENAME_BY_KIND["roadmap"] == assets.ROADMAP_FILENAME
    assert assets.ASSETS_FILENAME_BY_KIND["progress"] == assets.PROGRESS_FILENAME
    stem = assets.next_asset_stem("AI Agent")
    assert "AI_Agent" in stem.replace("-", "_") or "AI Agent" in stem
    assert len(stem) >= len("2000-01-01_")  # 日期前缀存在


def test_write_and_collect_index(tmp_path, monkeypatch):
    """write_asset_text 后 index 刷新出卡片；空态有引导。"""
    monkeypatch.setenv("CAREER_KIT_ASSETS_DIR", str(tmp_path / "CareerKit"))
    root = assets.ensure_assets_root()

    index = assets.rebuild_index()
    assert index.exists()
    text = index.read_text(encoding="utf-8")
    assert "还没有产出" in text or "会出现在这里" in text

    stem = "2026-10-26_AIAgent"
    assets.write_asset_text("research", "默认档案", f"{stem}.html", "<p>报告</p>")
    assets.write_asset_text("research", "默认档案", f"{stem}.md", "# 报告")
    assets.write_asset_text(
        "research",
        "默认档案",
        f"{stem}.json",
        '{"direction": "AI Agent", "counts": {"jd_samples": 8, "cases": 5, "source_fail": 1}}',
    )

    html_path = assets.kind_assets_dir("research", "默认档案") / f"{stem}.html"
    md_path = assets.kind_assets_dir("research", "默认档案") / f"{stem}.md"
    assert html_path.exists() and md_path.exists()
    text = assets.rebuild_index().read_text(encoding="utf-8")
    assert "AI Agent" in text      # 伴生 json 的 direction 成为卡片标题
    assert "8 条岗位" in text       # counts 数字进卡片
    assert "1 个源失败" in text      # 失败源数量如实展示
    assert stem in text             # 无 direction 时回退文件名主干

    # 按档案分组：新建另一个档案目录后仍能全部收录
    assets.write_asset_text("roadmap", "大厂冲刺", assets.ROADMAP_FILENAME, "<p>别的档案</p>")
    text = assets.rebuild_index().read_text(encoding="utf-8")
    assert "大厂冲刺" in text and "路线图" in text

    import shutil

    shutil.rmtree(root, ignore_errors=True)
