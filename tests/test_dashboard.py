"""export_dashboard 冒烟测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_export_dashboard_smoke(tmp_path, monkeypatch):
    """生成自包含 HTML，内嵌阶段进度与能力证据。"""
    import json as jsonlib

    import src.tools.profile as profile_module
    from src.server import checkin_task, export_dashboard, generate_tasks, intake
    from src.tools.roadmap import parse_roadmap

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
    import json as jsonlib

    import src.tools.profile as profile_module
    from src.models import CareerProfile
    from src.server import _render_roadmap_map
    from src.tools.roadmap import parse_roadmap

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


def test_progress_html_escapes_user_content(tmp_path, monkeypatch):
    """进度仪表盘：任务名/阶段名/证据含 HTML 时必须转义，防破版与注入。"""
    import json as jsonlib

    import src.tools.profile as profile_module
    from src.server import checkin_task, export_dashboard, generate_tasks, intake
    from src.tools.roadmap import parse_roadmap

    monkeypatch.setattr(profile_module, "PROFILE_DIR", tmp_path)

    intake("who", '{"name":"转义"}')
    profile = profile_module.load_profile()
    profile.plan = parse_roadmap(jsonlib.dumps({
        "roadmap": {"phases": [{"type": "learn", "name": "阶段<x>", "goal": "目标<y>",
                                "milestones": [{"name": "M1", "tasks": [
                                    {"name": "学习 vector<T> <img src=x onerror=alert(1)>"}]}]}]}
    }, ensure_ascii=False))
    profile.touch()
    profile_module.save_profile(profile)

    generate_tasks()
    checkin_task(task_id="task_001", status="completed", notes="备注<b>加粗</b>")
    out = export_dashboard()
    html = Path(Path(out.split("：")[1].split("\n")[0].strip())).read_text(encoding="utf-8")

    assert "<img src=x onerror=alert(1)>" not in html   # 原始 HTML 不得出现
    assert "vector&lt;T&gt;" in html                     # 任务名已转义
    assert "阶段&lt;x&gt;" in html                       # 阶段名已转义
    assert "备注&lt;b&gt;加粗&lt;/b&gt;" in html          # 能力证据 notes 已转义


def test_roadmap_map_json_script_close_defense(tmp_path, monkeypatch):
    """职业地图：内嵌 JSON 中 `</script>` 必须转义为 `<\\/script>`，防提前闭合。"""
    import json as jsonlib

    import src.tools.profile as profile_module
    from src.models import CareerProfile
    from src.server import _render_roadmap_map
    from src.tools.roadmap import parse_roadmap

    monkeypatch.setattr(profile_module, "PROFILE_DIR", tmp_path)

    profile = CareerProfile()
    profile.plan = parse_roadmap(jsonlib.dumps({
        "strategy_summary": "含闭合标签 </script><script>alert(1)</script>",
        "phases": [{"type": "learn", "name": "阶段一", "goal": "g",
                    "milestones": [{"name": "M", "tasks": [{"name": "任务甲"}]}]}],
    }, ensure_ascii=False))
    profile.touch()

    html = _render_roadmap_map(profile)

    assert "含闭合标签 <\\/script>" in html      # 数据中的闭合标签已被转义
    # application/json 数据块内不允许出现字面 </script>（会提前闭合）
    json_block = html.split('id="career-data">')[1].split("</script>")[0]
    assert "alert(1)" not in json_block or "<\\/script>" in json_block


def test_roadmap_map_js_escapes_interpolation(tmp_path, monkeypatch):
    """职业地图：JS 端 innerHTML 拼接必须走 esc() 转义函数。"""
    import src.tools.profile as profile_module
    from src.models import CareerProfile
    from src.server import _render_roadmap_map

    monkeypatch.setattr(profile_module, "PROFILE_DIR", tmp_path)

    html = _render_roadmap_map(CareerProfile())

    assert "function esc(" in html       # 转义函数已定义
    assert "esc(t.name)" in html         # 任务名拼接走转义
    assert "esc(ph.name)" in html        # 阶段名拼接走转义
    assert "esc(ph.jd_text" in html      # JD 文本拼接走转义

