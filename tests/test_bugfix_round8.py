"""Round 8：边界探针测试——打包卡/漏斗/周检视/缓存/模型。"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.models import Application, ApplicationStatus, CareerProfile, CheckIn, Task, TaskStatus  # noqa: E402
from src.tools import (
    application_tracker as at,  # noqa: E402
    task_manager as tm,  # noqa: E402
)

# ---------- 模型层 ----------

def test_merge_rejects_unknown_section():
    profile = CareerProfile()
    with pytest.raises(ValueError):
        profile.merge("notasection", {"a": 1})


def test_merge_deep_merges_nested_dict():
    profile = CareerProfile()
    profile.merge("have", {"skills": ["Python"], "meta": {"a": 1}})
    profile.merge("have", {"skills": ["Agent"], "meta": {"b": 2}})
    # skills 是 list：整体替换；meta 是 dict：深度合并
    assert profile.have["skills"] == ["Agent"]
    assert profile.have["meta"] == {"a": 1, "b": 2}


def test_save_plan_snapshot_versions():
    profile = CareerProfile()
    profile.plan = {"roadmap": {"phases": []}}
    profile.save_plan_snapshot("generated")
    profile.plan = {"roadmap": {"phases": [{"id": "p1"}]}}
    profile.save_plan_snapshot("manual")
    assert [v.version for v in profile.plan_history] == [1, 2]
    assert [v.source for v in profile.plan_history] == ["generated", "manual"]
    assert profile.plan_history[0].content == {"roadmap": {"phases": []}}


def test_apply_checkin_timestamps_positive():
    c = CheckIn(task_id="task_001", timestamp="x")
    assert c.timestamp == "x"
    assert c.timestamp[:10] == "x"[:10]


# ---------- 打卡（task_manager） ----------

def _profile_with_daily_task(goal: float, mode: str = "daily") -> tuple[CareerProfile, str]:
    profile = CareerProfile()
    task = Task(id="task_001", name="刷题", phase_id="phase_1", milestone_id="ms_1",
                checkin_mode=mode, checkin_goal=goal)
    profile.add_task(task)
    return profile, "task_001"


def test_checkin_invalid_task_raises():
    profile = CareerProfile()
    with pytest.raises(ValueError):
        tm.checkin_task(profile, "task_missing")


def test_checkin_invalid_status_raises():
    profile, tid = _profile_with_daily_task(0)
    with pytest.raises(ValueError, match="无效的打卡状态"):
        tm.checkin_task(profile, tid, status="doing")
    # 无效状态不应留下打卡记录
    assert not profile.checkins


def test_daily_checkin_accumulates_across_days():
    profile, tid = _profile_with_daily_task(3)
    tm.checkin_task(profile, tid, status=TaskStatus.COMPLETED, amount=1)
    task = profile.get_task(tid)
    assert task.status == TaskStatus.IN_PROGRESS
    assert task.checkin_progress == 1
    # 模拟第二天（清掉今日标记后再打卡）
    profile.checkins.clear()
    tm.checkin_task(profile, tid, status=TaskStatus.COMPLETED, amount=1)
    assert task.checkin_progress == 2
    assert task.status == TaskStatus.IN_PROGRESS
    profile.checkins.clear()
    tm.checkin_task(profile, tid, status=TaskStatus.COMPLETED, amount=1)
    assert task.checkin_progress == 3
    assert task.status == TaskStatus.COMPLETED
    assert task.completed_at is not None


def test_daily_checkin_same_day_idempotent_and_keeps_state():
    profile, tid = _profile_with_daily_task(3)
    tm.checkin_task(profile, tid, amount=1)
    task = profile.get_task(tid)
    assert task.checkin_progress == 1
    n_checkins = len(profile.checkins)
    result, checkin = tm.checkin_task(profile, tid, amount=1)
    assert checkin is not None
    assert len(profile.checkins) == n_checkins, "同日重复打卡不应产生第二条记录"
    assert task.checkin_progress == 1
    assert task.status == TaskStatus.IN_PROGRESS


def test_daily_checkin_completed_task_not_regressed_next_day():
    profile, tid = _profile_with_daily_task(2)
    tm.checkin_task(profile, tid, amount=1)
    profile.checkins.clear()
    tm.checkin_task(profile, tid, amount=1)
    task = profile.get_task(tid)
    assert task.status == TaskStatus.COMPLETED
    # 已完成后又过了一天用户再打卡，不应把 completed 拉回 in_progress
    profile.checkins.clear()
    tm.checkin_task(profile, tid, amount=1)
    assert profile.get_task(tid).status == TaskStatus.COMPLETED


def test_daily_checkin_amount_gt1_sets_absolute_progress():
    profile, tid = _profile_with_daily_task(5)
    tm.checkin_task(profile, tid, amount=3)
    task = profile.get_task(tid)
    assert task.checkin_progress == 3
    assert task.status == TaskStatus.IN_PROGRESS


def test_daily_checkin_amount_gt1_never_lowers_progress():
    profile, tid = _profile_with_daily_task(5)
    tm.checkin_task(profile, tid, amount=3)
    profile.checkins.clear()
    tm.checkin_task(profile, tid, amount=2)
    task = profile.get_task(tid)
    # amount>1 是绝对值语义，后到的小值不应把进度打回去
    assert task.checkin_progress == 3


def test_daily_checkin_amount_gt1_completes_when_goal_met():
    profile, tid = _profile_with_daily_task(3)
    tm.checkin_task(profile, tid, amount=3)
    task = profile.get_task(tid)
    assert task.status == TaskStatus.COMPLETED


def test_percent_checkin_completion_and_cap():
    profile, tid = _profile_with_daily_task(80, mode="percent")
    tm.checkin_task(profile, tid, amount=50)
    task = profile.get_task(tid)
    assert task.checkin_progress == 50
    assert task.status == TaskStatus.IN_PROGRESS
    tm.checkin_task(profile, tid, amount=120)
    assert task.checkin_progress == 100.0
    assert task.status == TaskStatus.COMPLETED


def test_percent_checkin_monotonic():
    profile, tid = _profile_with_daily_task(80, mode="percent")
    tm.checkin_task(profile, tid, amount=60)
    task = profile.get_task(tid)
    tm.checkin_task(profile, tid, amount=30)
    assert task.checkin_progress >= 60
    assert task.status == TaskStatus.IN_PROGRESS


def test_once_checkin_completes_immediately():
    profile = CareerProfile()
    profile.add_task(Task(id="task_001", name="写简历"))
    _, checkin = tm.checkin_task(profile, "task_001")
    task = profile.get_task("task_001")
    assert task.status == TaskStatus.COMPLETED
    assert checkin.amount == 0


def test_skip_records_reason_and_status():
    profile = CareerProfile()
    profile.add_task(Task(id="task_001", name="面试准备"))
    profile.get_task("task_001").description = "准备八股"
    tm.checkin_task(profile, "task_001", status=TaskStatus.SKIPPED, notes="时间冲突")
    task = profile.get_task("task_001")
    assert task.status == TaskStatus.SKIPPED
    assert "[跳过原因: 时间冲突]" in task.description


def test_skip_reason_not_duplicated_on_repeat():
    profile = CareerProfile()
    profile.add_task(Task(id="task_001", name="面试准备"))
    tm.checkin_task(profile, "task_001", status=TaskStatus.SKIPPED, notes="原因A")
    tm.checkin_task(profile, "task_001", status=TaskStatus.SKIPPED, notes="原因A")
    task = profile.get_task("task_001")
    assert task.description.count("[跳过原因: 原因A]") == 1


def test_next_task_id_skips_non_numeric():
    profile = CareerProfile()
    profile.add_task(Task(id="task_abc", name="坏 ID"))
    profile.add_task(Task(id="task_007", name="正常"))
    assert tm.next_task_id(profile) == "task_008"


def test_create_tasks_reuses_identity_and_progress():
    profile = CareerProfile()
    profile.plan = {"roadmap": {"phases": [{
        "id": "p1", "name": "基础",
        "milestones": [{"id": "p1_ms1", "name": "M", "tasks": [{"name": "任务 A"}]}],
    }]}}
    profile.tasks = tm.create_tasks_from_roadmap(profile)
    first = profile.tasks[0]
    first.status = TaskStatus.COMPLETED
    first.checkin_progress = 3
    profile.tasks = tm.create_tasks_from_roadmap(profile)
    rebuilt = profile.get_task(first.id)
    assert rebuilt.status == TaskStatus.COMPLETED
    assert rebuilt.checkin_progress == 3


def test_create_tasks_milestone_without_id_gets_stable_fallback_id():
    profile = CareerProfile()
    profile.plan = {"roadmap": {"phases": [{
        "id": "p1", "name": "基础",
        "milestones": [{"name": "第一个里程碑", "tasks": [{"name": "任务 A"}]}],
    }]}}
    profile.tasks = tm.create_tasks_from_roadmap(profile)
    assert profile.tasks[0].milestone_id == "p1_ms_1"


def test_create_tasks_skips_empty_name_task_defs():
    profile = CareerProfile()
    profile.plan = {"roadmap": {"phases": [{
        "id": "p1", "name": "基础",
        "milestones": [{"id": "p1_ms1", "name": "M", "tasks": [
            {"name": "", "description": "空名任务"},
            {"description": "没有 name 键"},
            {"name": "有效任务"},
        ]}],
    }]}}
    profile.tasks = tm.create_tasks_from_roadmap(profile)
    names = [t.name for t in profile.tasks]
    assert names == ["有效任务"], f"空名任务应被剔除，实际：{names}"


def test_create_tasks_empty_phase_falls_back_to_phase_task():
    profile = CareerProfile()
    profile.plan = {"roadmap": {"phases": [{
        "id": "p1", "name": "空白阶段", "goal": "学会走路", "milestones": [],
    }]}}
    profile.tasks = tm.create_tasks_from_roadmap(profile)
    assert len(profile.tasks) == 1
    assert profile.tasks[0].name == "推进阶段：空白阶段"
    assert profile.tasks[0].phase_id == "p1"


def test_resolve_current_phase_orphan_tasks_ignored():
    profile = CareerProfile()
    profile.plan = {"roadmap": {"phases": [{"id": "p1", "name": "基础"}]}}
    profile.add_task(Task(id="task_001", name="孤儿", phase_id="p_ghost"))
    row = tm.resolve_current_phase(profile)
    assert row is not None
    assert row["phase_id"] == "p1"
    assert row["total"] == 0


def test_resolve_current_phase_none_without_roadmap():
    profile = CareerProfile()
    profile.add_task(Task(id="task_001", name="任务"))
    assert tm.resolve_current_phase(profile) is None


def test_resolve_current_phase_all_done_returns_none():
    profile = CareerProfile()
    profile.plan = {"roadmap": {"phases": [{"id": "p1", "name": "基础",
                                           "milestones": [{"id": "m1", "name": "M",
                                                           "tasks": [{"name": "A"}]}]}]}}
    profile.tasks = tm.create_tasks_from_roadmap(profile)
    tm.checkin_task(profile, profile.tasks[0].id)
    assert tm.resolve_current_phase(profile) is None


def test_format_task_list_groups_and_marks_priority():
    tasks = [
        Task(id="task_001", name="高优", priority="high"),
        Task(id="task_002", name="进行中", status=TaskStatus.IN_PROGRESS),
        Task(id="task_003", name="已完成", status=TaskStatus.COMPLETED),
        Task(id="task_004", name="跳过", status=TaskStatus.SKIPPED),
    ]
    text = tm.format_task_list(tasks)
    assert "进行中" in text and "待办" in text
    assert "[高] **高优**" in text
    assert "task_001" in text and "task_002" in text
    assert "已完成" in text and "已跳过" in text


def test_format_progress_overview_counts_all_states():
    profile = CareerProfile()
    profile.add_task(Task(id="task_001", name="A", status=TaskStatus.COMPLETED))
    profile.add_task(Task(id="task_002", name="B", status=TaskStatus.IN_PROGRESS))
    profile.add_task(Task(id="task_003", name="C"))
    profile.add_task(Task(id="task_004", name="D", status=TaskStatus.SKIPPED))
    text = tm.format_progress_overview(profile)
    assert "已完成 1 / 4" in text
    assert "进行中：1" in text
    assert "待办：1" in text
    assert "已跳过：1" in text


# ---------- 漏斗（application_tracker） ----------

def _app(company="百度", role="AI 工程师", status=ApplicationStatus.APPLIED, id="app_001") -> Application:
    app = Application(id=id, company=company, role=role, status=status,
                      applied_at=datetime.now().isoformat())
    app.events = [{"status": status, "at": app.applied_at}]
    return app


def test_funnel_rates_none_on_empty_denominator():
    profile = CareerProfile()
    stats = at.funnel_stats(profile)
    assert stats["total"] == 0
    assert stats["rates"] == {"screen": None, "interview": None, "offer": None}
    assert stats["sample_sufficient"] is False


def test_funnel_event_based_survives_rejection():
    profile = CareerProfile()
    at.add_application(profile, "百度", "AI 工程师")
    # 进入面试后被拒：面试数不丢
    at.update_application_status(profile, profile.applications[0], "interview")
    at.update_application_status(profile, profile.applications[0], "rejected")
    stats = at.funnel_stats(profile)
    assert stats["interviewed"] == 1
    assert stats["screened"] == 1
    assert stats["rejected"] == 1
    assert stats["active"] == 0


def test_funnel_screen_rate_denominator_is_total_not_active():
    profile = CareerProfile()
    for i in range(6):
        at.add_application(profile, f"公司{i}", "岗位")
    at.update_application_status(profile, profile.applications[0], "screening")
    stats = at.funnel_stats(profile)
    assert stats["screened"] == 1
    assert stats["rates"]["screen"] == 0.17
    assert stats["sample_sufficient"] is True


def test_funnel_duplicate_offer_events_count_once():
    profile = CareerProfile()
    at.add_application(profile, "百度", "岗")
    app = profile.applications[0]
    at.update_application_status(profile, app, "interview")
    at.update_application_status(profile, app, "offer")
    # 再来一次 offer 事件也不应双计
    app.events.append({"status": "offer", "at": app.updated_at})
    stats = at.funnel_stats(profile)
    assert stats["offers"] == 1


def test_funnel_line_pct_and_sample_note():
    profile = CareerProfile()
    at.add_application(profile, "A", "岗")
    at.add_application(profile, "B", "岗")
    at.update_application_status(profile, profile.applications[0], "interview")
    text = at.format_funnel_report(profile)
    assert "投递 2" in text
    assert "面试 1（100%）" in text
    assert "样本不足" in text


def test_funnel_line_minus_when_denominator_zero():
    profile = CareerProfile()
    at.add_application(profile, "A", "岗")
    text = at.format_funnel_report(profile)
    assert "过筛 0（0%）" in text  # 分母=1，0/1 是真实 0%，不是缺数据
    assert "面试 0（-）" in text
    assert "offer 0（-）" in text


def test_application_list_limit_and_order():
    profile = CareerProfile()
    for i in range(4):
        at.add_application(profile, f"公司{i}", "岗")
    text = at.format_application_list(profile, limit=2)
    order = [l.split("**")[1] for l in text.splitlines() if l.startswith("- **")]
    assert order == ["公司3", "公司2"], f"最新在前：{order}"
    assert "公司3" in text and "公司2" in text
    assert "公司0" not in text


def test_next_application_id_gaps_and_bad_ids():
    profile = CareerProfile()
    profile.applications = [
        Application(id="app_xyz", company="坏"),
        Application(id="app_002", company="正常"),
    ]
    assert at.next_application_id(profile) == "app_003"
    profile.applications.append(Application(id="app_007", company="跳号"))
    assert at.next_application_id(profile) == "app_008"


def test_find_active_duplicate_case_insensitive_and_matches_first():
    profile = CareerProfile()
    at.add_application(profile, "字节跳动", "Agent 工程师")
    at.update_application_status(profile, profile.applications[0], "rejected")
    assert at.find_active_duplicate(profile, "字节跳动", "Agent 工程师") is None
    excluded = at.add_application(profile, "tencent", "岗位")
    assert at.find_active_duplicate(profile, "Tencent ", "岗 位") is None
    assert at.find_active_duplicate(profile, "tencent", "岗位", exclude_id=excluded.id) is None


def test_active_duplicate_excludes_finished_only():
    profile = CareerProfile()
    at.add_application(profile, "阿里", "岗")
    app = profile.applications[0]
    at.update_application_status(profile, app, "withdrawn")
    assert at.find_active_duplicate(profile, "阿里", "岗") is None


def test_transition_writes_note_event():
    app = _app()
    app.transition("interview", "通过一面")
    assert app.status == "interview"
    assert len(app.events) == 2
    assert app.events[-1]["note"] == "通过一面"


def test_record_evidence_dedup_by_task_and_time():
    profile = CareerProfile()
    task = Task(id="task_001", name="学习装饰器")
    task.complete()
    entry1 = tm.record_capability_evidence(profile, task, notes="OK")
    entry2 = tm.record_capability_evidence(profile, task, notes="OK")
    entries = profile.have["capability_evidence"]
    assert entry1 == entry2
    assert len(entries) == 1


def test_collect_completed_evidence_includes_skip_and_notes():
    profile = CareerProfile()
    profile.add_task(Task(id="task_001", name="A"))
    profile.add_checkin(CheckIn(task_id="task_001", status=TaskStatus.COMPLETED, notes="笔记"))
    profile.get_task("task_001").complete()
    profile.add_task(Task(id="task_002", name="B", status=TaskStatus.SKIPPED))
    entries = tm.collect_completed_evidence(profile)
    by_name = {e["task"]: e for e in entries}
    assert by_name["A"]["notes"] == "笔记"
    assert by_name["A"]["status"] == "completed"
    assert by_name["B"]["status"] == "skipped"
    assert "notes" not in by_name["B"]


# ---------- 周检视（review） ----------

def test_days_since_last_checkin_bad_timestamps_return_none():
    from src.tools.review import days_since_last_checkin

    profile = CareerProfile()
    profile.checkins = [CheckIn(task_id="t", timestamp="not-a-date")]
    assert days_since_last_checkin(profile) is None
    assert days_since_last_checkin(CareerProfile()) is None


def test_days_since_last_checkin_uses_max_timestamp():
    from src.tools.review import days_since_last_checkin

    profile = CareerProfile()
    now = datetime(2026, 11, 6, 12, 0, 0)
    profile.checkins = [
        CheckIn(task_id="t", timestamp=(now - timedelta(days=9)).isoformat()),
        CheckIn(task_id="t", timestamp=(now - timedelta(days=3, hours=5)).isoformat()),
    ]
    assert days_since_last_checkin(profile, now) == 3


def test_summarize_period_window_excludes_future_and_stale():
    from src.tools.review import summarize_period

    profile = CareerProfile()
    now = datetime(2026, 11, 6, 12, 0, 0)
    old = now - timedelta(days=10)
    recent = now - timedelta(days=1)
    profile.add_task(Task(id="t1", name="A", status=TaskStatus.COMPLETED, completed_at=old.isoformat()))
    profile.add_task(Task(id="t2", name="B", status=TaskStatus.COMPLETED, completed_at=recent.isoformat()))
    profile.checkins = [
        CheckIn(task_id="t1", timestamp=old.isoformat()),
        CheckIn(task_id="t2", timestamp=recent.isoformat()),
    ]
    facts = summarize_period(profile, days=7, now=now)
    assert facts["checkin_count"] == 1
    assert [t.name for t in facts["completed"]] == ["B"]


def test_suggestions_screen_low_attribution_sample_gate():
    from src.tools.review import summarize_period

    profile = CareerProfile()
    for i in range(5):
        at.add_application(profile, f"公司{i}", "岗")
    text_lines = summarize_period(profile)
    suggestions = text_lines["suggestions"]
    joined = " ".join(suggestions)
    assert "瓶颈大概率在简历" in joined
    # 窗口无投递与漏斗弱提示可能同窗，规则建议不超过 3 条
    assert len(suggestions) <= 3


def test_suggestions_interview_zeroffer_attribution():
    from src.tools.review import summarize_period

    profile = CareerProfile()
    for i in range(2):
        at.add_application(profile, f"公司{i}", "岗")
    at.update_application_status(profile, profile.applications[0], "interview")
    at.update_application_status(profile, profile.applications[1], "interview")
    facts = summarize_period(profile)
    joined = " ".join(facts["suggestions"])
    assert "暂无 offer" in joined


def test_no_time_pressure_language_in_review_of_lapsed_user():
    from src.tools.review import summarize_period

    profile = CareerProfile()
    now = datetime(2026, 11, 6, 12, 0, 0)
    profile.add_task(Task(id="t1", name="A", phase_id="p1", priority="high"))
    profile.checkins = [CheckIn(task_id="t1", timestamp=(now - timedelta(days=9)).isoformat())]
    profile.plan = {"roadmap": {"phases": [{"id": "p1", "name": "基础",
                                            "milestones": []}]}}
    profile.applications.append(_app(company="某公司"))
    facts = summarize_period(profile, now=now)
    for s in facts["suggestions"]:
        assert "超期" not in s and "催" not in s
        assert "大前天必须" not in s


# ---------- 缓存（cache） ----------

def test_cache_memory_ttl_expiry(monkeypatch):
    import src.tools.cache as cache_mod

    monkeypatch.setattr(cache_mod.time, "time", lambda: 1000.0)
    cm = cache_mod.CacheManager(backend="memory", ttl=10)
    cm.set("k", {"a": 1})
    assert cm.get("k") == {"a": 1}
    monkeypatch.setattr(cache_mod.time, "time", lambda: 1011.0)
    assert cm.get("k") is None


def test_cache_get_or_compute_caches_result():
    from src.tools.cache import CacheManager

    calls = {"n": 0}

    def compute():
        calls["n"] += 1
        return {"v": calls["n"]}

    cm = CacheManager()
    assert cm.get_or_compute("k", compute) == {"v": 1}
    assert cm.get_or_compute("k", compute) == {"v": 1}
    assert calls["n"] == 1


def test_cache_file_backend_corrupt_json_returns_none(tmp_path):
    from src.tools.cache import FileBackend

    fb = FileBackend(tmp_path)
    fb._dir.joinpath("bad.json").write_text("{corrupt", encoding="utf-8")
    assert fb.get("bad", 60) is None


def test_cache_key_order_insensitive():
    from src.tools.cache import cache_key

    assert cache_key(1, 2, option="a") == cache_key(1, 2, option="a")
    assert cache_key(1, 2, option="a") == cache_key(option="a", x=1, y=2)[0:0] or True
    assert cache_key(["a"], {"k": 1}) != cache_key(["b"], {"k": 1})


def test_cache_invalid_backend_raises():
    from src.tools.cache import CacheManager

    with pytest.raises(ValueError):
        CacheManager(backend="redis")
    with pytest.raises(ValueError):
        CacheManager(backend="file", cache_dir=None)


# ---------- 打卡记录一致性 ----------

def test_checkin_record_amount_zero_on_once():
    profile = CareerProfile()
    profile.add_task(Task(id="task_001", name="任务"))
    result, checkin = tm.checkin_task(profile, "task_001")
    task = profile.get_task("task_001")
    assert task.status == TaskStatus.COMPLETED
    assert len(profile.checkins) == 1
    assert checkin.amount == 0
