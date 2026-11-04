"""零安装演示：随包附带的职业地图必须可定位。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.demo import demo_html, main  # noqa: E402


def test_demo_html_is_bundled():
    target = demo_html()
    assert target is not None
    assert target.name == "career-map.html"
    assert target.is_file()


def test_demo_no_open_prints_path(capsys):
    assert main(["--no-open"]) == 0
    out = capsys.readouterr().out
    assert "career-map.html" in out
