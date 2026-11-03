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
from src.models import CareerProfile, Task  # noqa: E402
from src.web import build_state, create_server  # noqa: E402


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
    return profile


def test_build_state_exposes_roadmap_and_playbook(temp_profile):
    profile_module.save_profile(_profile())

    state = build_state()

    assert state["profile"]
    assert state["start_level"] == "小厂"
    assert state["phases"][0]["tasks"][0]["how_to"] == ["先想 10 分钟"]
    assert state["phases"][0]["tasks"][0]["done_criteria"] == "独立写出 5 题"
    assert state["total_tasks"] == 1


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
