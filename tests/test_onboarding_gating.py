"""建档门禁回归——简历解析不跳过摸排、一次性简介不重复、摘要缺失可读。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from src.core.state import State, resolve_state  # noqa: E402
from src.guidance import build_guide, mark_goal_confirmed  # noqa: E402
from src.models import CareerProfile  # noqa: E402
from src.tools import profile as profile_module  # noqa: E402

READY_HAVE = {
    "core_skills": [
        {
            "skill": "Python",
            "evidence": "用户确认独立完成课程项目",
            "user_verified": True,
            "authorship": "self_written",
            "control_level": 8,
        }
    ],
    "self_assessment": {"resume_trust": "high", "notes": "技能可核验"},
}


def test_resume_parse_stays_in_profile_until_have_is_confirmed():
    """B1：简历素材写入 who 后不能直接跳到第 2 步目标定位。"""
    from src.server import finalize_profile, intake, parse_resume, start_session

    start_session()
    resume = Path(profile_module.PROFILE_DIR) / "resume.md"
    resume.parent.mkdir(parents=True, exist_ok=True)
    resume.write_text("精通 Python，做过爬虫项目", encoding="utf-8")
    parse_resume(str(resume))

    # 模型按解析结果先写 who——只写素材，不等于完成建档。
    intake("who", json.dumps({"name": "林舟"}, ensure_ascii=False))

    profile = profile_module.load_profile()
    snapshot = resolve_state(profile)
    assert snapshot.state is State.PROFILE_COLLECTING
    assert snapshot.stage_index == 1
    assert snapshot.stage_name == "职业档案构建"
    assert snapshot.next_tool == "intake(have)"
    assert any(b.code == "profile_probe_required" for b in snapshot.blockers)

    guide = build_guide(profile)
    assert guide.index == 1
    assert guide.status == "profile"
    assert "intake(have)" in guide.next_action

    blocked = json.loads(finalize_profile())
    assert blocked["isError"] is True
    assert blocked["details"]["next_tool"] == "intake(have)"


def test_confirmed_have_unlocks_target_stage():
    """B1：have 写入并补齐自评后，才允许进入目标定位。"""
    from src.server import intake, parse_resume, start_session

    start_session()
    resume = Path(profile_module.PROFILE_DIR) / "resume.md"
    resume.parent.mkdir(parents=True, exist_ok=True)
    resume.write_text("精通 Python，做过爬虫项目", encoding="utf-8")
    parse_resume(str(resume))

    intake("who", json.dumps({"name": "林舟"}, ensure_ascii=False))
    assert resolve_state(profile_module.load_profile()).stage_index == 1

    intake("have", json.dumps(READY_HAVE, ensure_ascii=False))

    snapshot = resolve_state(profile_module.load_profile())
    assert snapshot.state is State.PROFILE_COLLECTING
    assert snapshot.stage_index == 2
    assert snapshot.next_tool == "explore_goals"


def test_parse_resume_does_not_repeat_user_brief():
    """B2：首屏简介只发一次，parse_resume 不重复注入 [USER_BRIEF]。"""
    from src.server import parse_resume, start_session

    session = start_session()
    assert "[USER_BRIEF]" in session

    resume = Path(profile_module.PROFILE_DIR) / "resume.md"
    resume.parent.mkdir(parents=True, exist_ok=True)
    resume.write_text("Python 爬虫项目", encoding="utf-8")
    out = parse_resume(str(resume))

    assert "[USER_BRIEF]" not in out
    assert "Career Kit 是你的 AI 职业陪练" not in out
    assert "候选素材" in out


def test_finalize_summary_renders_blank_name_readably():
    """B4：姓名为空时摘要不显示 `name=`，回退为「未填写」。"""
    from src.server import finalize_profile

    profile = CareerProfile(
        who={"name": ""},
        have={"skills": []},
        want={"target_role": "AI Agent"},
    )
    mark_goal_confirmed(profile)
    profile_module.save_profile(profile)

    out = finalize_profile()
    assert "name=未填写" in out
    assert "name=，" not in out
    assert "name=\n" not in out
