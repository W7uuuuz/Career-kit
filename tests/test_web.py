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
    profile.guidance = {"goal_confirmed_at": "2026-11-09T00:00:00"}
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
    assert state["phases"][0]["type"] == "learn"
    assert state["phases"][0]["type_label"] == "学习"
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
        BaselinePlan,
        CompanyEntry,
        CompanyPool,
        EvidenceRun,
        ExecutionPlan,
        ExecutionState,
        GapReport,
        HardRequirement,
        MarketBaseline,
        ProfileSnapshot,
        RequirementItem,
        RequirementProfile,
        TargetSpec,
    )
    from src.core.artifacts.store import ArtifactStore

    class _ProfileArtifact(ProfileSnapshot):
        meta: ArtifactMeta

    class _TargetArtifact(TargetSpec):
        meta: ArtifactMeta

    store = ArtifactStore()
    report_dir = kind_assets_dir("evidence", profile_name)
    html_path = report_dir / "evidence.html"
    md_path = report_dir / "evidence.md"
    json_path = report_dir / "evidence.json"
    html_path.write_text("<html>证据</html>", encoding="utf-8")
    md_path.write_text("# 证据", encoding="utf-8")
    json_path.write_text("{}", encoding="utf-8")

    target = TargetSpec(role="AI Agent", direction="AI Agent")
    profile_id = store.save(_ProfileArtifact(
        meta=ArtifactMeta(
            id="pf_test", stage="profile", profile_name=profile_name,
            created_at="2026-11-07T23:59:55",
        ),
        name="张三",
        who={"name": "张三"},
        summary="测试档案",
    ))
    target_id = store.save(_TargetArtifact(
        meta=ArtifactMeta(
            id="ts_test", stage="target", profile_name=profile_name,
            created_at="2026-11-07T23:59:56",
            inputs={"profile_id": profile_id},
        ),
        **target.model_dump(),
    ))
    market_id = store.save(MarketBaseline(
        meta=ArtifactMeta(
            id="mb_test", stage="market_baseline", profile_name=profile_name,
            created_at="2026-11-07T23:59:57",
            inputs={"target_spec_id": target_id},
        ),
        target_spec=target,
    ))
    gap_id = store.save(GapReport(
        meta=ArtifactMeta(
            id="gr_test", stage="gap", profile_name=profile_name,
            created_at="2026-11-07T23:59:58",
        ),
        profile_snapshot_id=profile_id,
        market_baseline_id=market_id,
        match_score=60,
    ))
    baseline_id = store.save(BaselinePlan(
        meta=ArtifactMeta(
            id="bp_test", stage="baseline_plan", profile_name=profile_name,
            created_at="2026-11-07T23:59:59",
        ),
        gap_report_id=gap_id,
        roadmap={"phases": [{"name": "基础"}]},
    ))
    pool_id = store.save(CompanyPool(
        meta=ArtifactMeta(
            id="cp_test", stage="company_pool", profile_name=profile_name,
            created_at="2026-11-08T00:00:00",
            inputs={"baseline_plan_id": baseline_id},
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
            validation={"status": "saved"},
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
    execution_id = store.save(ExecutionState(
        meta=ArtifactMeta(
            id="es_test", stage="execution", profile_name=profile_name,
            created_at="2026-11-08T00:00:04",
        ),
        execution_plan_id=plan_id,
    ))
    return {
        "profile": profile_id,
        "target_spec": target_id,
        "market_baseline": market_id,
        "gap": gap_id,
        "baseline_plan": baseline_id,
        "company_pool": pool_id,
        "evidence": evidence_id,
        "requirement": requirement_id,
        "execution_plan": plan_id,
        "execution_state": execution_id,
    }


def test_build_state_alignment_absent_without_core_state(temp_profile):
    """档案没有 core_state 时，alignment 也要存在且不崩。"""
    profile_module.save_profile(_profile())

    alignment = build_state()["alignment"]

    assert alignment["stage"] == ""
    assert alignment["company_pool"] is None
    assert alignment["evidence"] is None
    assert alignment["requirement"] is None
    assert alignment["execution_plan"] is None
    assert alignment["next_tool"] == "finalize_profile"


def test_build_state_alignment_reads_artifacts(temp_profile):
    from src.tools.profile import get_active_profile_name

    profile = _profile()
    profile_name = get_active_profile_name()
    ids = _save_alignment_artifacts(profile_name)
    profile.core_state = {
        "stage": "executing",
        "profile_id": ids["profile"],
        "target_spec_id": ids["target_spec"],
        "market_baseline_id": ids["market_baseline"],
        "gap_report_id": ids["gap"],
        "baseline_plan_id": ids["baseline_plan"],
        "company_pool_id": ids["company_pool"],
        "evidence_run_id": ids["evidence"],
        "requirement_profile_id": ids["requirement"],
        "execution_plan_id": ids["execution_plan"],
        "execution_state_id": ids["execution_state"],
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
    assert alignment["next_tool"] == "get_next_tasks"


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
    from src.web import DIST_DIR

    html = (DIST_DIR / "index.html").read_text(encoding="utf-8")
    assert '<div id="app">' in html
    scripts = list((DIST_DIR / "assets").glob("*.js"))
    assert scripts, "Vue 构建产物缺失"
    bundle = scripts[0].read_text(encoding="utf-8")
    assert "企业适配" in bundle


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


def test_server_requires_token_and_writes_checkin(temp_profile, monkeypatch, tmp_path):
    import src.web as web

    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(
        "<!doctype html><title>Career Kit 控制台</title>__CK_TOKEN__",
        encoding="utf-8",
    )
    (dist / "assets" / "app.js").write_text("fetch('api/checkin')", encoding="utf-8")
    monkeypatch.setattr(web, "DIST_DIR", dist)

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
        with urllib.request.urlopen(f"{base}/assets/app.js") as res:
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


def test_missing_dist_returns_build_hint(temp_profile, monkeypatch, tmp_path):
    import src.web as web

    monkeypatch.setattr(web, "DIST_DIR", tmp_path / "missing-dist")
    server, _token = create_server(port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    base = f"http://{host}:{port}"
    try:
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(f"{base}/")
        assert exc.value.code == 503
        assert "前端尚未构建" in exc.value.read().decode("utf-8")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_build_state_tolerates_damaged_roadmap(temp_profile):
    """damaged roadmap（phases/milestones/tasks 类型不对）不能让控制台崩。"""
    profile = _profile()
    profile.plan = {"roadmap": {"phases": "not-a-list"}}
    profile_module.save_profile(profile)

    state = build_state()

    assert state["phases"] == []

    broken = _profile()
    broken.tasks = []
    broken.plan = {
        "roadmap": {
            "phases": [
                "bad-phase",
                {"id": "p1", "name": "P1", "milestones": "bad-milestones"},
                {
                    "id": "p2",
                    "name": "P2",
                    "milestones": [
                        {"id": "m1", "name": "M1", "tasks": "bad-tasks"},
                        {
                            "id": "m2",
                            "name": "M2",
                            "tasks": ["bad-task", {"name": "T", "description": "d"}],
                        },
                    ],
                },
            ]
        }
    }
    profile_module.save_profile(broken)

    state = build_state()

    assert [phase["id"] for phase in state["phases"]] == ["p1", "p2"]
    assert state["phases"][1]["milestone_tasks"] == [
        {"name": "T", "desc": "d", "priority": "medium", "done_criteria": ""}
    ]


def test_console_writes_trigger_core_sync(temp_profile, monkeypatch):
    """update_task/add_application_entry/undo_task 成功后要刷新对应 artifact。"""
    import src.core.sync as core_sync

    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        core_sync,
        "sync_execution_state",
        lambda name: calls.append(("exec", name)) or "",
    )
    monkeypatch.setattr(
        core_sync,
        "sync_application_state",
        lambda name: calls.append(("app", name)) or "",
    )
    profile_module.save_profile(_profile())

    from src.web import add_application_entry, undo_task, update_task

    state = update_task("task_001", {"name": "改过的任务"})
    assert state["phases"][0]["tasks"][0]["name"] == "改过的任务"
    assert ("exec", "default") in calls

    state = add_application_entry({"company": "新公司", "role": "Agent 实习"})
    assert state["applications"][-1]["company"] == "新公司"
    assert ("app", "default") in calls

    undo_task("task_001")
    assert calls.count(("exec", "default")) >= 2


def test_console_sync_failure_does_not_block_write(temp_profile, monkeypatch):
    """sync 失败只在 state 里留 warning，控制台写操作仍成功。"""
    import src.core.sync as core_sync

    def _failing_sync(profile_name: str) -> str:
        raise RuntimeError("artifact store down")

    monkeypatch.setattr(core_sync, "sync_execution_state", _failing_sync)
    monkeypatch.setattr(core_sync, "sync_application_state", _failing_sync)
    profile_module.save_profile(_profile())

    from src.web import add_application_entry, undo_task, update_task

    state = update_task("task_001", {"name": "改过的任务"})
    assert "同步失败" in state["sync_warning"]

    state = add_application_entry({"company": "新公司", "role": "Agent 实习"})
    assert "同步失败" in state["sync_warning"]

    undo_task("task_001")  # 不应抛异常


def test_checkin_sync_failure_does_not_block(temp_profile, monkeypatch):
    import src.core.sync as core_sync

    def _failing_sync(profile_name: str) -> str:
        raise RuntimeError("artifact store down")

    monkeypatch.setattr(core_sync, "sync_execution_state", _failing_sync)
    profile_module.save_profile(_profile())
    server, token = create_server(port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    base = f"http://{host}:{port}"
    try:
        request = urllib.request.Request(
            f"{base}/api/checkin",
            data=json.dumps(
                {"task_id": "task_001", "status": "completed", "amount": 1}
            ).encode(),
            headers={"X-CK-Token": token, "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request) as res:
            data = json.loads(res.read())
        assert data["ok"] is True
        assert "同步失败" in data["state"]["sync_warning"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_roadmap_route_exposes_execution_plan_mode(temp_profile):
    """控制台 /roadmap 应把已校准的执行版标记出来。"""
    profile = _profile()
    profile.core_state = {
        "stage": "executing",
        "requirement_profile_id": "rp_test",
        "execution_plan_id": "ep_test",
    }
    profile_module.save_profile(profile)
    server, token = create_server(port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    base = f"http://{host}:{port}"
    try:
        with urllib.request.urlopen(f"{base}/roadmap?token={token}") as res:
            html = res.read().decode("utf-8")
        assert 'name="career-kit-plan-mode" content="execution"' in html
        assert "执行版：已按确认企业与 JD 需求校准" in html
        assert "rp_test" in html and "ep_test" in html
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_state_route_returns_readable_json_on_error(temp_profile, monkeypatch):
    import src.web as web

    def _boom(*args, **kwargs):
        raise RuntimeError("坏数据")

    monkeypatch.setattr(web, "build_state", _boom)
    server, token = create_server(port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    base = f"http://{host}:{port}"
    try:
        request = urllib.request.Request(
            f"{base}/api/state", headers={"X-CK-Token": token}
        )
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(request)
        assert exc.value.code == 500
        body = json.loads(exc.value.read().decode("utf-8"))
        assert "状态构建失败" in body["error"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
