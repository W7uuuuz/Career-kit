"""export_dashboard 冒烟测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_export_dashboard_smoke(tmp_path, monkeypatch):
    """生成自包含 HTML，内嵌阶段进度与能力证据。"""
    import src.tools.profile as profile_module
    from src.server import checkin_task, export_dashboard, generate_tasks, intake
    from src.tools.roadmap import parse_roadmap
    from src.models import CareerProfile
    import json as jsonlib

    monkeypatch.setattr(profile_module, "PROFILE_DIR", tmp_path)

    intake("who", '{"name":"冒烟"}')
    profile = profile_module.load_profile()
    profile.plan = parse_roadmap(jsonlib.dumps({
        "roadmap": {"phases": [{"type": "learn", "name": "基础", "goal": "入门",
                                "milestones": [{"name": "M1", "tasks": [{"name": "任务A"}, {"name": "任务B"}]}]}]}
    }, ensure_ascii=False))
    profile.touch()
    profile_module.save_profile(profile)

    generate_tasks()
    result = checkin_task(task_id="task_001", status="completed", notes="冒烟打卡")
    assert "已打卡" in result or "已跳过" not in result

    out = export_dashboard()
    assert "career_kit_dashboard.html" in out

    html = Path(Path(out.split("：")[1].split("\n")[0].strip())).read_text(encoding="utf-8")
    assert "基础" in html          # 阶段名
    assert "冒烟打卡" in html      # 能力证据 notes 已内嵌
    assert "task-deadline" not in html and "超期" not in html  # 无时间概念残留


def test_roadmap_map_renders_start_strategy_milestones(tmp_path, monkeypatch):
    """职业地图渲染回归：起点层级 / 策略 / 里程碑名称必须进入 HTML。

    锁死三个曾出现的渲染 bug：
    - #start-level 从未被赋值（永远显示 —）
    - #strategy 从未被赋值
    - 里程碑只显示 M1/M2（用 id 硬转，不显示真实名称）
    """
    import src.tools.profile as profile_module
    from src.server import _render_roadmap_map
    from src.tools.roadmap import parse_roadmap
    from src.models import CareerProfile
    import json as jsonlib

    monkeypatch.setattr(profile_module, "PROFILE_DIR", tmp_path)

    profile = CareerProfile.model_validate_json(
        (tmp_path / "default.json").read_text(encoding="utf-8")
    ) if (tmp_path / "default.json").exists() else CareerProfile()
    profile.gap = {"start_level": "小厂"}
    profile.plan = parse_roadmap(jsonlib.dumps({
        "strategy_summary": "先补协作再冲大厂",
        "phases": [{"type": "learn", "name": "阶段一", "goal": "打基础",
                    "milestones": [{"name": "里程碑甲",
                                    "tasks": [{"name": "任务甲"}]}]}],
    }, ensure_ascii=False))
    profile.touch()

    html = _render_roadmap_map(profile)

    assert '"start_level": "小厂"' in html            # 起点层级进入数据
    assert "先补协作再冲大厂" in html                   # 策略进入数据
    assert "里程碑甲" in html                          # 里程碑名称进入数据
    assert "milestone_names" in html                   # 前端按名称渲染
    assert "getElementById('start-level')" in html     # 前端真的写入起点层级
    assert "getElementById('strategy')" in html        # 前端真的写入策略

