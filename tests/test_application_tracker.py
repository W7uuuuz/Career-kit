"""求职漏斗回归：记录、去重、事件口径统计。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

import src.tools.profile as profile_module
from src.models import Application, CareerProfile
from src.tools.application_tracker import (
    add_application,
    application_summary,
    find_active_duplicate,
    format_application_list,
    format_funnel_report,
    funnel_stats,
    next_application_id,
    update_application_status,
)


@pytest.fixture()
def temp_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(profile_module, "PROFILE_DIR", tmp_path)
    return tmp_path


def _profile() -> CareerProfile:
    return CareerProfile()


def _app(app_id: str, company: str, role: str = "", events: list[str] | None = None,
         status: str | None = None) -> Application:
    app = Application(id=app_id, company=company, role=role)
    app.events = [{"status": s, "at": "2026-10-20T10:00:00"} for s in (events or ["applied"])]
    app.status = status or (events[-1] if events else "applied")
    return app


# === ID 与新增 ===


def test_next_application_id_sequence():
    p = _profile()
    assert next_application_id(p) == "app_001"
    p.add_application(_app("app_001", "字节"))
    assert next_application_id(p) == "app_002"


def test_add_application_defaults_and_first_event():
    p = _profile()
    app = add_application(p, company="字节跳动", role="Agent 实习")
    assert app.id == "app_001"
    assert app.status == "applied"
    assert app.applied_at and app.updated_at
    assert app.events[0]["status"] == "applied"
    assert len(p.applications) == 1


# === 去重 ===


def test_find_active_duplicate_matches_company_role_case_insensitive():
    p = _profile()
    p.applications = [_app("app_001", "字节跳动", "Agent 实习")]
    assert find_active_duplicate(p, "字节跳动", "agent 实习") is not None
    assert find_active_duplicate(p, "腾讯", "前端") is None


def test_duplicate_check_ignores_finished_records():
    p = _profile()
    p.applications = [_app("app_001", "字节跳动", "实习", events=["applied", "rejected"])]
    assert find_active_duplicate(p, "字节跳动", "实习") is None


# === 状态更新 ===


def test_update_status_appends_event_only_on_change():
    p = _profile()
    app = add_application(p, company="字节", role="实习")
    assert update_application_status(p, app, "applied") is False
    assert len(app.events) == 1
    assert update_application_status(p, app, "interview", note="一面通过") is True
    assert app.status == "interview"
    assert len(app.events) == 2
    assert app.events[-1]["note"] == "一面通过"


# === 漏斗统计（事件口径）===


def test_funnel_stats_zero_state():
    p = _profile()
    stats = funnel_stats(p)
    assert stats["total"] == 0
    assert stats["rates"] == {"screen": None, "interview": None, "offer": None}
    assert stats["sample_sufficient"] is False


def test_funnel_event_based_counts_rejected_after_interview():
    """面试后被拒仍计入面试数——漏斗不许失真。"""
    p = _profile()
    p.applications = [
        _app("app_001", "A", events=["applied", "screening", "interview", "rejected"]),
        _app("app_002", "B", events=["applied", "screening", "rejected"]),
        _app("app_003", "C", events=["applied"]),  # 还在等结果
    ]
    stats = funnel_stats(p)
    assert stats["total"] == 3
    assert stats["active"] == 1           # app_003 还在等
    assert stats["screened"] == 2
    assert stats["interviewed"] == 1      # app_001 面试过
    assert stats["offers"] == 0
    assert stats["rejected"] == 2
    assert stats["rates"]["screen"] == 0.67
    assert stats["rates"]["interview"] == 0.5
    assert stats["rates"]["offer"] == 0.0
    assert stats["sample_sufficient"] is False


def test_funnel_sample_flag_turns_on():
    p = _profile()
    p.applications = [_app(f"app_{i:03d}", f"C{i}") for i in range(1, 6)]
    assert funnel_stats(p)["sample_sufficient"] is True


def test_withdrawn_still_counts_as_submitted():
    p = _profile()
    p.applications = [_app("app_001", "A", events=["applied", "withdrawn"], status="withdrawn")]
    stats = funnel_stats(p)
    assert stats["total"] == 1
    assert stats["active"] == 0


# === 文本报告 ===


def test_format_funnel_report_empty_and_filled():
    p = _profile()
    assert "暂无投递记录" in format_funnel_report(p)
    p.applications = [_app("app_001", "A", events=["applied", "interview"])]
    text = format_funnel_report(p)
    assert "面试 1" in text
    assert "事件历史" in text or "事件" in text


def test_format_application_list_newest_first():
    p = _profile()
    p.applications = [_app("app_001", "乙"), _app("app_002", "甲")]
    text = format_application_list(p)
    assert text.index("甲") < text.index("乙")


def test_application_summary_shape():
    app = _app("app_001", "字节", "实习", events=["applied"])
    s = application_summary(app)
    assert s["id"] == "app_001" and s["status"] == "applied"
    assert s["events"][0]["status"] == "applied"


# === 工具契约 ===


def test_record_application_create_and_funnel(temp_profile):
    from src.server import record_application

    result = json.loads(record_application(company="字节跳动", role="Agent 实习"))
    assert not result.get("isError"), result
    assert result["application"]["id"] == "app_001"
    assert result["context"]["funnel"]["total"] == 1
    profile = profile_module.load_profile()
    assert profile.applications[0].company == "字节跳动"


def test_record_application_rejects_active_duplicate(temp_profile):
    from src.server import record_application

    record_application(company="字节跳动", role="Agent 实习")
    result = json.loads(record_application(company="字节跳动", role="Agent 实习"))
    assert result.get("isError") is True
    assert result["code"] == "DUPLICATE_APPLICATION"
    assert result["details"]["application_id"] == "app_001"
    assert len(profile_module.load_profile().applications) == 1


def test_record_application_rejects_after_rejected(temp_profile):
    """已拒绝的记录不构成重复保护：可以再投再记。"""
    from src.server import record_application

    first = json.loads(record_application(company="字节", status="rejected"))
    assert not first.get("isError"), first
    second = json.loads(record_application(company="字节"))
    assert not second.get("isError"), second
    assert profile_module.load_profile().applications[-1].id == "app_002"


def test_record_application_update_status_flow(temp_profile):
    from src.server import record_application

    record_application(company="字节", role="实习")
    result = json.loads(
        record_application(company="字节", role="实习", status="interview", application_id="app_001")
    )
    assert not result.get("isError"), result
    assert result["application"]["status"] == "interview"
    profile = profile_module.load_profile()
    app = profile.get_application("app_001")
    assert [e["status"] for e in app.events] == ["applied", "interview"]


def test_record_application_soft_hint_on_interview(temp_profile):
    from src.server import record_application

    record_application(company="字节", role="实习")
    result = json.loads(
        record_application(company="字节", role="实习", status="interview",
                           application_id="app_001")
    )
    assert "trigger_insight" in result["message"]
    assert result["next_steps"][0] == "trigger_insight"


def test_record_application_update_missing_id(temp_profile):
    from src.server import record_application

    result = json.loads(record_application(company="字节", application_id="app_099"))
    assert result.get("isError") is True
    assert result["code"] == "MISSING_DATA"


def test_record_application_invalid_status(temp_profile):
    from src.server import record_application

    result = json.loads(record_application(company="字节", status="面试中"))
    assert result.get("isError") is True
    assert result["code"] == "INVALID_SECTION"


def test_record_application_empty_company(temp_profile):
    from src.server import record_application

    result = json.loads(record_application(company="  "))
    assert result.get("isError") is True
    assert result["code"] == "MISSING_DATA"


def test_get_progress_shows_funnel(temp_profile):
    from src.server import get_progress, record_application

    record_application(company="字节", role="实习")
    record_application(company="字节", role="实习", status="interview", application_id="app_001")

    out = get_progress()
    assert "求职漏斗" in out
    assert "面试 1" in out


def test_get_progress_without_tasks_but_applications(temp_profile):
    """没建任务也能先看漏斗。"""
    from src.server import get_progress, record_application

    record_application(company="字节", role="实习")
    out = get_progress()
    assert "求职漏斗" in out
