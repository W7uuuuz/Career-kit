"""本地控制台：状态构建、token 鉴权、打卡写回档案。"""

from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

import src.tools.profile as profile_module  # noqa: E402
from src.models import Application, CareerProfile, Task  # noqa: E402
from src.web import build_parser, build_state, create_server  # noqa: E402


@pytest.fixture()
def temp_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(profile_module, "PROFILE_DIR", tmp_path)
    return tmp_path


def _profile() -> CareerProfile:
    profile = CareerProfile()
    profile.who = {"name": "测试"}
    profile.summary = "应届生"
    profile.gap = {"start_level": "小厂"}
    profile.plan = {"roadmap": {"strategy_summary": "先补基础", "phases": [{
        "id": "phase_1", "name": "基础补齐", "type": "learn", "goal": "能手写",
        "milestones": [{"id": "phase_1_ms_1", "name": "算法"}],
    }]}}
    profile.tasks = [Task(
        id="task_001", name="LeetCode 热题 100", phase_id="phase_1",
        milestone_id="phase_1_ms_1", checkin_mode="daily", checkin_goal=5,
        how_to=["先想 10 分钟"], done_criteria="独立写出 5 题",
        resources=[{"label": "LeetCode", "url": "https://leetcode.cn/"}],
    )]
    profile.research = {
        "report_md": "report.md",
        "report_html": "report.html",
        "generated_at": "2026-11-03",
        "counts": {"jd_samples": 10, "cases": 3},
        "source_status": [{"source": "boss", "status": "failed"}],
    }
    profile.applications = [Application(id="app_001", company="某公司", role="Agent 实习")]
    return profile


def test_cli_accepts_open_flag():
    """安装脚本/README 使用 --open，CLI 必须接受。"""
    args = build_parser().parse_args(["--open"])
    assert args.open is True and args.no_open is False


def test_asset_route_is_token_protected_and_scoped(temp_profile):
    from urllib.parse import quote

    from src.assets import get_assets_root

    root = get_assets_root()
    root.mkdir(parents=True, exist_ok=True)
    asset = root / "hello.txt"
    asset.write_text("hello", encoding="utf-8")

    server, token = create_server(port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    base = f"http://{host}:{port}"
    try:
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(f"{base}/api/asset?path={quote(str(asset))}")
        assert exc.value.code == 403
        with urllib.request.urlopen(
            f"{base}/api/asset?path={quote(str(asset))}&token={token}"
        ) as res:
            assert res.read() == b"hello"
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(
                f"{base}/api/asset?path={quote(str(temp_profile / 'x.txt'))}&token={token}"
            )
        assert exc.value.code == 403
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_build_state_exposes_roadmap_and_playbook(temp_profile):
    profile_module.save_profile(_profile())

    state = build_state()

    assert state["profile"]
    assert state["start_level"] == "小厂"
    assert state["phases"][0]["tasks"][0]["how_to"] == ["先想 10 分钟"]
    assert state["phases"][0]["tasks"][0]["done_criteria"] == "独立写出 5 题"
    assert state["total_tasks"] == 1
    assert state["research"]["counts"]["jd_samples"] == 10
    assert state["research"]["failed_sources"] == ["boss"]
    assert state["applications"][0]["company"] == "某公司"


def test_server_requires_token_and_writes_checkin(temp_profile):
    profile_module.save_profile(_profile())
    server, token = create_server(port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    base = f"http://{host}:{port}"
    try:
        with urllib.request.urlopen(f"{base}/api/health") as res:
            assert json.loads(res.read())["ok"] is True

        with urllib.request.urlopen(f"{base}/") as res:
            html = res.read().decode("utf-8")
        assert token in html and "Career Kit 控制台" in html
        with urllib.request.urlopen(f"{base}/app.js") as res:
            assert "api/checkin" in res.read().decode("utf-8")

        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(f"{base}/api/state")
        assert exc.value.code == 403

        request = urllib.request.Request(
            f"{base}/api/state", headers={"X-CK-Token": token}
        )
        with urllib.request.urlopen(request) as res:
            state = json.loads(res.read())
        assert state["total_tasks"] == 1

        request = urllib.request.Request(
            f"{base}/api/checkin",
            data=json.dumps({"task_id": "task_001", "status": "completed", "amount": 1}).encode(),
            headers={"X-CK-Token": token, "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request) as res:
            data = json.loads(res.read())
        assert data["ok"] is True
        assert data["state"]["phases"][0]["tasks"][0]["checkin_progress"] == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
