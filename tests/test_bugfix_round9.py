"""Round 9：教育标签误报 / 洞察调整边界探针。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.education import (  # noqa: E402
    canonical_education,
    education_match_beta,
    education_search_words,
    normalize_education_tag,
)
from src.models import CareerProfile, Task  # noqa: E402
from src.tools.insight import apply_adjustment, build_insight_prompt  # noqa: E402

# ---------- 学历标签归一 ----------

def test_tag_common_compound_forms():
    assert normalize_education_tag("双非本")["tag"] == "双非本"
    assert normalize_education_tag("211硕")["tag"] == "211硕"
    assert normalize_education_tag("985本")["tag"] == "985本"


def test_major_word_not_mistaken_for_zhuanke():
    # BUG-3：「专业」不能当「专科」
    info = normalize_education_tag("软件工程专业")
    assert info["degree"] != "专科", info
    info2 = normalize_education_tag("双非软件工程专业上岸")
    assert info2["tier"] == "双非"
    assert info2["degree"] not in ("专科",), "「专业」不应触发专科学历"


def test_user_self_reference_not_bachelor():
    # BUG-4：「本人」的「本」不能当「本科」
    info = normalize_education_tag("本人211上岸")
    assert info["tier"] == "211"
    assert info["degree"] != "本科", info
    info2 = normalize_education_tag("本人，双非，27届拿到offer")
    assert info2["tier"] == "双非"
    assert info2["year"] == "27届"
    assert info2["degree"] != "本科"


def test_real_zhuanke_still_recognized():
    assert normalize_education_tag("专科")["degree"] == "专科"
    assert normalize_education_tag("大专")["degree"] == "专科"
    # 「专升本」语义上是升入本科，最终学历按本科
    assert normalize_education_tag("专升本上岸")["degree"] == "本科"


def test_degree_priority_long_words_first():
    assert normalize_education_tag("27届研究生")["degree"] == "硕士"
    assert normalize_education_tag("大数据专硕")["degree"] == "硕士"
    assert normalize_education_tag("博士在读")["degree"] == "博士"


def test_canonical_education_rejects_unrecognized():
    with pytest.raises(ValueError):
        canonical_education("")
    with pytest.raises(ValueError):
        canonical_education("不知道")


def test_canonical_education_accepts_known_forms():
    assert canonical_education("双非本")["tag"] == "双非本"
    assert canonical_education("211硕")["tag"] == "211硕"
    assert canonical_education("专科")["tag"] == "专科"


def test_match_beta_scores():
    cond = canonical_education("双非本")
    assert education_match_beta(cond, "双非本，27届上岸字节") == 3
    assert education_match_beta(cond, "双非硕，投了一周") == 2
    assert education_match_beta(cond, "211本") == 1  # 仅层级同层，也算部分匹配
    assert education_match_beta(cond, "今天天气不错") == 0
    deg_cond = canonical_education("硕士")
    assert education_match_beta(deg_cond, "双非硕") == 1


def test_search_words_expansion():
    assert set(education_search_words(canonical_education("双非本"))) >= {
        "双非", "二本", "本科"}
    assert education_search_words(canonical_education("专科")) >= ["专科", "大专", "专"][:2]


# ---------- 洞察调整 ----------

def _profile_with_task() -> CareerProfile:
    profile = CareerProfile()
    profile.add_task(Task(id="task_001", name="学习基础", phase_id="phase_1"))
    return profile


def test_apply_add_task_assigns_new_id():
    profile = _profile_with_task()
    result = {
        "trigger_type": "event",
        "summary": "加面试冲刺",
        "adjustment_type": "auto",
        "changes": [{
            "type": "add_task",
            "details": {"name": "八股冲刺清单", "description": "高频八股"},
        }],
    }
    _, adjustment = apply_adjustment(profile, result)
    added = [t for t in profile.tasks if t.id == "task_002"]
    assert added and added[0].name == "八股冲刺清单"
    assert adjustment.changes[0]["task_id"] == "task_002"


def test_apply_add_task_skips_empty_name():
    profile = _profile_with_task()
    result = {
        "trigger_type": "event",
        "summary": "空调整",
        "changes": [{"type": "add_task", "details": {}}, {"type": "add_task"}],
    }
    _, adjustment = apply_adjustment(profile, result)
    assert all(t.name for t in profile.tasks), "不应产生空名任务"
    assert adjustment.changes == []


def test_apply_remove_task():
    profile = _profile_with_task()
    result = {"changes": [{"type": "remove_task", "task_id": "task_001"}]}
    apply_adjustment(profile, result)
    assert profile.get_task("task_001") is None
    # 不存在的任务：不崩、不误记
    result2 = {"changes": [{"type": "remove_task", "task_id": "task_ghost"}]}
    _, adjustment = apply_adjustment(profile, result2)
    assert adjustment.changes == []


def test_apply_modify_task():
    profile = _profile_with_task()
    result = {
        "changes": [{
            "type": "modify_task", "task_id": "task_001",
            "details": {"name": "学习基础（加量）", "priority": "high"},
        }],
    }
    _, adjustment = apply_adjustment(profile, result)
    task = profile.get_task("task_001")
    assert task.name == "学习基础（加量）"
    assert task.priority == "high"
    assert adjustment.changes[0]["task_name"] == "学习基础（加量）"


def test_apply_trigger_type_enum_gating():
    profile = _profile_with_task()
    result = {"trigger_type": "proactive", "changes": []}
    _, adjustment = apply_adjustment(profile, result)
    assert adjustment.trigger_type == ""


def test_completed_phase_ids_only_when_all_done():
    from src.models import TaskStatus
    from src.tools.insight import completed_phase_ids

    profile = CareerProfile()
    profile.add_task(Task(id="task_001", name="A", phase_id="p1", status=TaskStatus.COMPLETED))
    profile.add_task(Task(id="task_002", name="B", phase_id="p1", status=TaskStatus.SKIPPED))
    profile.add_task(Task(id="task_003", name="C", phase_id="p2"))
    profile.add_task(Task(id="task_004", name="孤儿", phase_id=""))
    assert completed_phase_ids(profile) == ["p1"]


def test_insight_prompt_contains_facts():
    profile = _profile_with_task()
    profile.who = {"name": "张三"}
    profile.want = {"target_role": "AI Agent", "city": "上海", "graduation_year": "27届"}
    prompt = build_insight_prompt(profile, trigger_type="event",
                                  event_description="进入字节面试")
    assert "AI Agent" in prompt
    assert "进入字节面试" in prompt
    assert "0/1 个任务已完成" in prompt


def test_insight_prompt_stage_audit():
    profile = _profile_with_task()
    prompt = build_insight_prompt(profile, trigger_type="stage_audit")
    assert "stage_audit" in prompt
