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

import src.paths as paths_module  # noqa: E402
import src.tools.profile as profile_module  # noqa: E402
from src.models import Application, CareerProfile, Task  # noqa: E402
from src.web import build_parser, build_state, create_server  # noqa: E402


@pytest.fixture()
def temp_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(profile_module, "PROFILE_DIR", tmp_path)
    monkeypatch.setattr(paths_module, "PROFILE_DIR", tmp_path)
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
    from src.assets import kind_assets_dir
    from src.tools.profile import get_active_profile_name

    profile_module.save_profile(_profile())
    report_dir = kind_assets_dir("research", get_active_profile_name())
    (report_dir / "2026-11-03_AI_Agent.json").write_text(
        json.dumps({
            "direction": "AI Agent",
            "generated_at": "2026-11-03",
            "counts": {"jd_samples": 8, "cases": 2},
            "source_status": [{"source": "boss", "status": "failed"}],
        }, ensure_ascii=False),
        encoding="utf-8",
    )

    state = build_state()

    assert state["profile"]
    assert state["start_level"] == "小厂"
    assert state["phases"][0]["tasks"][0]["how_to"] == ["先想 10 分钟"]
    assert state["phases"][0]["tasks"][0]["done_criteria"] == "独立写出 5 题"
    assert state["total_tasks"] == 1
    assert state["research"]["counts"]["jd_samples"] == 10
    assert state["research"]["failed_sources"] == ["boss"]
    assert state["applications"][0]["company"] == "某公司"
    assert state["reports"][0]["direction"] == "AI Agent"


def _save_alignment_artifacts(profile_name: str) -> dict[str, str]:
    from src.assets import kind_assets_dir
    from src.core.artifacts.models import (
        ArtifactMeta,
        CompanyEntry,
        CompanyPool,
        EvidenceRun,
        ExecutionPlan,
        HardRequirement,
        RequirementItem,
        RequirementProfile,
        TargetSpec,
    )
    from src.core.artifacts.store import ArtifactStore

    store = ArtifactStore()
    report_dir = kind_assets_dir("evidence", profile_name)
    html_path = report_dir / "evidence.html"
    md_path = report_dir / "evidence.md"
    json_path = report_dir / "evidence.json"
    html_path.write_text("<html>证据</html>", encoding="utf-8")
    md_path.write_text("# 证据", encoding="utf-8")
    json_path.write_text("{}", encoding="utf-8")

    target = TargetSpec(role="AI Agent", direction="AI Agent")
    pool_id = store.save(CompanyPool(
        meta=ArtifactMeta(
            id="cp_test", stage="company_pool", profile_name=profile_name,
            created_at="2026-11-08T00:00:00",
        ),
        target_spec=target,
        companies=[
            CompanyEntry(
                id="c1", name="字节", tier="大厂", industry="互联网",
                scrapable=True, status="confirmed",
            ),
            CompanyEntry(id="c2", name="某厂", tier="中厂", industry="互联网", scrapable=False),
        ],
        counts={"total": 2, "scrapable": 1, "not_scrapable": 1},
    ))
    evidence_id = store.save(EvidenceRun(
        meta=ArtifactMeta(
            id="ev_test", stage="evidence", profile_name=profile_name,
            created_at="2026-11-08T00:00:01",
        ),
        target_spec=target,
        company_pool_id=pool_id,
        counts={"kept_jobs": 3, "interviews": 2},
        confidence={"jd": "medium", "interview": "low"},
        report_paths={"html": str(html_path), "md": str(md_path), "json": str(json_path)},
    ))
    requirement_id = store.save(RequirementProfile(
        meta=ArtifactMeta(
            id="rp_test", stage="requirement", profile_name=profile_name,
            created_at="2026-11-08T00:00:02",
        ),
        evidence_run_id=evidence_id,
        confidence_jd="medium",
        confidence_interview="low",
        high_frequency=[RequirementItem(
            term="Python", category="技能", jd_count=3, jd_frequency=1.0,
            company_count=2, company_frequency=1.0,
        )],
        hard_requirements=[HardRequirement(evidence_id="JD001", education="本科")],
    ))
    plan_id = store.save(ExecutionPlan(
        meta=ArtifactMeta(
            id="ep_test", stage="execution_plan", profile_name=profile_name,
            created_at="2026-11-08T00:00:03",
        ),
        requirement_profile_id=requirement_id,
        strategy_summary="先补基础",
        roadmap={"phases": [{"name": "基础"}, {"name": "项目"}]},
        applied=True,
        diff_summary="新增 2 个任务",
    ))
    return {
        "company_pool": pool_id,
        "evidence": evidence_id,
        "requirement": requirement_id,
        "execution_plan": plan_id,
    }


def test_build_state_alignment_absent_for_legacy_profile(temp_profile):
    """旧档案没有 core_state 时，alignment 也要存在且不崩。"""
    profile_module.save_profile(_profile())

    alignment = build_state()["alignment"]

    assert alignment["stage"] == ""
    assert alignment["company_pool"] is None
    assert alignment["evidence"] is None
    assert alignment["requirement"] is None
    assert alignment["execution_plan"] is None
    assert alignment["next_tool"] == "select_target_companies"


def test_build_state_alignment_reads_artifacts(temp_profile):
    from src.tools.profile import get_active_profile_name

    profile = _profile()
    profile_name = get_active_profile_name()
    ids = _save_alignment_artifacts(profile_name)
    profile.core_state = {
        "stage": "executing",
        "company_pool_id": ids["company_pool"],
        "evidence_run_id": ids["evidence"],
        "requirement_profile_id": ids["requirement"],
        "execution_plan_id": ids["execution_plan"],
    }
    profile_module.save_profile(profile)

    alignment = build_state()["alignment"]

    assert alignment["stage"] == "executing"
    assert alignment["company_pool"]["id"] == ids["company_pool"]
    assert alignment["company_pool"]["counts"]["total"] == 2
    assert alignment["company_pool"]["scrapable"] == ["字节"]
    assert alignment["company_pool"]["not_scrapable"] == ["某厂"]
    assert alignment["evidence"]["counts"]["kept_jobs"] == 3
    assert alignment["evidence"]["confidence"]["jd"] == "medium"
    assert alignment["evidence"]["report_html"].startswith("/api/asset?path=")
    assert alignment["evidence"]["report_md"].startswith("/api/asset?path=")
    assert alignment["evidence"]["index"].startswith("/api/asset?path=")
    assert alignment["requirement"]["high_frequency_count"] == 1
    assert alignment["requirement"]["hard_requirement_count"] == 1
    assert alignment["requirement"]["confidence_jd"] == "medium"
    assert alignment["execution_plan"]["applied"] is True
    assert alignment["execution_plan"]["phase_count"] == 2
    assert alignment["execution_plan"]["strategy_summary"] == "先补基础"
    assert alignment["execution_plan"]["diff_summary"] == "新增 2 个任务"
    assert alignment["next_tool"] == ""


def test_build_state_alignment_falls_back_to_latest(temp_profile):
    from src.tools.profile import get_active_profile_name

    profile = _profile()
    ids = _save_alignment_artifacts(get_active_profile_name())
    profile.core_state = {"stage": "executing"}
    profile_module.save_profile(profile)

    alignment = build_state()["alignment"]

    assert alignment["company_pool"]["id"] == ids["company_pool"]
    assert alignment["evidence"]["id"] == ids["evidence"]
    assert alignment["requirement"]["id"] == ids["requirement"]
    assert alignment["execution_plan"]["id"] == ids["execution_plan"]


def test_index_page_contains_alignment_card():
    from src.web import INDEX_FILE

    html = INDEX_FILE.read_text(encoding="utf-8")
    assert "企业适配" in html
    assert 'id="alignment"' in html


def test_task_edit_and_application_entry(temp_profile):
    profile_module.save_profile(_profile())
    server, token = create_server(port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    base = f"http://{host}:{port}"

    def post(path: str, payload: dict) -> dict:
        request = urllib.request.Request(
            base + path,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"X-CK-Token": token, "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request) as res:
            return json.loads(res.read())

    try:
        data = post("/api/task", {
            "task_id": "task_001",
            "name": "改过的任务",
            "how_to": ["先做", "再检查"],
            "done_criteria": "通过",
            "checkin_mode": "daily",
            "checkin_goal": 3,
        })
        task = data["state"]["phases"][0]["tasks"][0]
        assert task["name"] == "改过的任务"
        assert task["how_to"] == ["先做", "再检查"]
        assert task["checkin_mode"] == "daily"

        data = post("/api/application", {
            "company": "新公司", "role": "Agent 实习", "status": "applied",
        })
        assert data["state"]["applications"][-1]["company"] == "新公司"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


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

        with urllib.request.urlopen(f"{base}/roadmap?token={token}") as res:
            roadmap_html = res.read().decode("utf-8")
        assert "__CK_API_BASE__" not in roadmap_html
        assert f"http://{host}:{port}" in roadmap_html

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
