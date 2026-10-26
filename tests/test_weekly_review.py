"""周检视回归：窗口统计、事实提示、规则化建议。时间由测试注入，保证确定性。"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

import src.tools.profile as profile_module
from src.models import Application, CareerProfile, CheckIn, Task
from src.tools.review import (
    days_since_last_checkin,
    format_weekly_review,
    summarize_period,
)

NOW = datetime(2026, 10, 25, 12, 0, 0)


@pytest.fixture()
def temp_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(profile_module, "PROFILE_DIR", tmp_path)
    return tmp_path


def _profile() -> CareerProfile:
    profile = CareerProfile()
    profile.plan = {
        "roadmap": {
            "phases": [
                {"id": "phase_1", "name": "Agent 基础"},
                {"id": "phase_2", "name": "RAG 项目"},
            ]
        }
    }
    return profile


def _ts(day: int, hour: int = 10) -> str:
    return f"2026-10-{day:02d}T{hour:02d}:00:00"


def test_days_since_last_checkin_none_and_value():
    profile = _profile()
    assert days_since_last_checkin(profile, now=NOW) is None
    profile.checkins = [CheckIn(task_id="task_001", timestamp=_ts(20))]
    # 10-20 12:00 到 10-25 12:00 = 5 天
    assert days_since_last_checkin(profile, now=NOW) == 5


def test_summarize_period_window_filters_tasks():
    profile = _profile()
    t_old = Task(id="task_001", name="窗口外完成", phase_id="phase_1",
                 status="completed", completed_at=_ts(10))
    t_now = Task(id="task_002", name="窗口内完成", phase_id="phase_1",
                 status="completed", completed_at=_ts(23))
    t_open = Task(id="task_003", name="未开始", phase_id="phase_2", priority="high")
    profile.tasks = [t_old, t_now, t_open]
    profile.checkins = [
        CheckIn(task_id="task_001", timestamp=_ts(10)),
        CheckIn(task_id="task_002", timestamp=_ts(22)),
        CheckIn(task_id="task_002", timestamp=_ts(24)),
    ]

    facts = summarize_period(profile, days=7, now=NOW)
    assert facts["checkin_count"] == 2
    assert [t.id for t in facts["completed"]] == ["task_002"]
    assert facts["active_days"] == ["2026-10-22", "2026-10-24"]


def test_summarize_period_phase_progress_start_vs_now():
    profile = _profile()
    profile.tasks = [
        Task(id="task_001", name="旧完成", phase_id="phase_1", status="completed",
             completed_at=_ts(10)),
        Task(id="task_002", name="新完成", phase_id="phase_2", status="completed",
             completed_at=_ts(23)),
        Task(id="task_003", name="未开始", phase_id="phase_2"),
    ]
    facts = summarize_period(profile, days=7, now=NOW)
    rows = {r["name"]: r for r in facts["phase_rows"]}
    assert rows["Agent 基础"]["done_at_start"] == 1 and rows["Agent 基础"]["done_now"] == 1
    assert rows["RAG 项目"]["done_at_start"] == 0 and rows["RAG 项目"]["done_now"] == 1


def test_summarize_period_application_delta_and_funnel():
    profile = _profile()
    for i, (cid, events) in enumerate([
        ("甲", ["applied", "screening"]),
        ("乙", ["applied"]),
        ("丙", ["applied", "interview", "offer"]),
    ], 1):
        app = Application(
            id=f"app_{i:03d}", company=cid, applied_at=_ts(22),
            updated_at=_ts(22), events=[], status="applied",
        )
        if cid == "丙":
            app.applied_at = _ts(5)  # 窗口外的旧投递，事件在窗口内
        app.events = [
            {"status": s, "at": _ts(22 if cid != "丙" else 23)}
            for s in events
        ]
        profile.applications.append(app)

    facts = summarize_period(profile, days=7, now=NOW)
    delta = facts["funnel_delta"]
    assert delta["new_applications"] == 2           # 甲、乙
    assert delta["screened"] == 2                   # 甲、丙（事件口径）
    assert delta["interviewed"] == 1
    assert delta["offers"] == 1
    assert facts["funnel_now"]["total"] == 3


def test_suggestion_no_applications_and_stalled():
    profile = _profile()
    t_open = Task(id="task_001", name="未开始", phase_id="phase_1", priority="high")
    profile.tasks = [t_open]
    profile.checkins = [CheckIn(task_id="task_001", timestamp=_ts(10))]  # 15 天前

    facts = summarize_period(profile, days=7, now=NOW)
    text = "\n".join(facts["suggestions"])
    assert "还没有投递记录" in text
    assert "15 天前" in text
    assert "phase_1" not in format_weekly_review(profile, facts)  # 内部 id 不露出


def test_suggestion_low_screen_rate_needs_sample():
    profile = _profile()
    for i in range(1, 6):
        app = Application(id=f"app_{i:03d}", company=f"C{i}", applied_at=_ts(5),
                          updated_at=_ts(5), events=[{"status": "applied", "at": _ts(5)}],
                          status="applied")
        profile.applications.append(app)
    facts = summarize_period(profile, days=30, now=NOW)
    assert any("简历" in s for s in facts["suggestions"])


def test_suggestion_interview_without_offer():
    profile = _profile()
    for i in range(1, 7):
        events = [{"status": "applied", "at": _ts(5)}, {"status": "screening", "at": _ts(8)},
                  {"status": "interview", "at": _ts(12)}]
        app = Application(id=f"app_{i:03d}", company=f"C{i}", applied_at=_ts(5),
                          updated_at=_ts(12), events=events, status="interview")
        profile.applications.append(app)
    facts = summarize_period(profile, days=30, now=NOW)
    assert any("interview_preparation" in s or "专项准备" in s for s in facts["suggestions"])


def test_format_weekly_review_renders_sections_and_no_deadline():
    profile = _profile()
    profile.tasks = [
        Task(id="task_001", name="完成 A", phase_id="phase_1", status="completed",
             completed_at=_ts(23)),
        Task(id="task_002", name="未开始 B", phase_id="phase_1", priority="high"),
    ]
    profile.checkins = [CheckIn(task_id="task_001", timestamp=_ts(23))]
    app = Application(id="app_001", company="字节", role="实习", applied_at=_ts(22),
                      updated_at=_ts(22), events=[{"status": "applied", "at": _ts(22)}],
                      status="applied")
    profile.applications.append(app)

    facts = summarize_period(profile, days=7, now=NOW)
    text = format_weekly_review(profile, facts)

    assert "## 周检视" in text
    assert "### 执行" in text
    assert "### 求职进展" in text
    assert "打卡 1 次" in text
    assert "完成 A" in text
    assert "字节" in text
    assert "超期" not in text and "逾期" not in text  # 语义红线：不做时间压迫


def test_bad_timestamps_are_tolerated():
    profile = _profile()
    profile.tasks = [
        Task(id="task_001", name="坏时间戳", phase_id="phase_1", status="completed",
             completed_at="不是时间"),
    ]
    profile.checkins = [CheckIn(task_id="task_001", timestamp="also-bad")]
    facts = summarize_period(profile, days=7, now=NOW)
    assert facts["completed"] == [] and facts["checkin_count"] == 0


# === 工具契约 ===


def test_get_weekly_review_empty_profile(temp_profile):
    from src.server import get_weekly_review

    result = json.loads(get_weekly_review())
    assert result["context"]["phase"] == "nothing_to_review"


def test_get_weekly_review_renders_and_marks_last_review(temp_profile):
    from src.server import get_weekly_review

    profile = profile_module.load_profile()
    profile.tasks = [Task(id="task_001", name="任务 A", phase_id="p1",
                          status="completed", completed_at=_ts(23))]
    profile.checkins = [CheckIn(task_id="task_001", timestamp=_ts(23))]
    profile_module.save_profile(profile)

    out = get_weekly_review()
    assert "## 周检视" in out
    assert "任务 A" in out

    saved = profile_module.load_profile()
    assert saved.last_review_at  # 调用后记录检视时间


def test_get_weekly_review_days_rejected(temp_profile):
    """越界 days 直接报错并说明合法范围（不静默收敛、不装作 normal）。"""
    import json

    from src.server import get_weekly_review

    profile = profile_module.load_profile()
    profile.tasks = [Task(id="task_001", name="任务 A", phase_id="p1",
                          status="completed", completed_at=_ts(23))]
    profile.checkins = [CheckIn(task_id="task_001", timestamp=_ts(23))]
    profile_module.save_profile(profile)

    for bad in (0, 999):
        result = json.loads(get_weekly_review(days=bad))
        assert result.get("isError") is True
        assert result["code"] == "INVALID_PARAM"
        assert "1-90" in result["message"]
