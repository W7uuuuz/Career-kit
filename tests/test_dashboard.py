"""控制台职业地图渲染测试（不再生成静态 HTML 文件）。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_roadmap_map_renders_start_strategy_milestones(tmp_path, monkeypatch):
    """职业地图渲染回归：起点层级 / 策略 / 里程碑名称必须进入 HTML。"""
    import json as jsonlib

    import src.tools.profile as profile_module
    from src.models import CareerProfile
    from src.tools.dashboard import render_roadmap_map
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

    html = render_roadmap_map(profile)

    assert '"start_level": "小厂"' in html
    assert "先补协作再冲大厂" in html
    assert "里程碑甲" in html
    assert '"type_label": "学习"' in html
    assert "milestone_names" in html
    assert "getElementById('start-level')" in html
    assert "getElementById('strategy')" in html


def test_roadmap_map_json_script_close_defense(tmp_path, monkeypatch):
    """内嵌 JSON 中 `</script>` 必须转义为 `<\\/script>`，防提前闭合。"""
    import json as jsonlib

    import src.tools.profile as profile_module
    from src.models import CareerProfile
    from src.tools.dashboard import render_roadmap_map
    from src.tools.roadmap import parse_roadmap

    monkeypatch.setattr(profile_module, "PROFILE_DIR", tmp_path)

    profile = CareerProfile()
    profile.plan = parse_roadmap(jsonlib.dumps({
        "strategy_summary": "含闭合标签 </script><script>alert(1)</script>",
        "phases": [{"type": "learn", "name": "阶段一", "goal": "g",
                    "milestones": [{"name": "M", "tasks": [{"name": "任务甲"}]}]}],
    }, ensure_ascii=False))
    profile.touch()

    html = render_roadmap_map(profile)

    assert "含闭合标签 <\\/script>" in html
    json_block = html.split('id="career-data">')[1].split("</script>")[0]
    assert "alert(1)" not in json_block or "<\\/script>" in json_block


def test_roadmap_map_js_escapes_interpolation(tmp_path, monkeypatch):
    """JS 端 innerHTML 拼接必须走 esc() 转义函数。"""
    import src.tools.profile as profile_module
    from src.models import CareerProfile
    from src.tools.dashboard import render_roadmap_map

    monkeypatch.setattr(profile_module, "PROFILE_DIR", tmp_path)

    html = render_roadmap_map(CareerProfile())

    assert "function esc(" in html
    assert "esc(t.name)" in html
    assert "esc(ph.name)" in html
    assert "esc(ph.jd_text" in html
    assert "esc(ph.type_label" in html


def test_roadmap_jd_structured_and_current_phase_fallback(tmp_path, monkeypatch):
    """JD 列表按条目可读渲染；无任务时默认激活第一段。"""
    import json as jsonlib

    import src.tools.profile as profile_module
    from src.models import CareerProfile
    from src.tools.dashboard import render_roadmap_map
    from src.tools.roadmap import parse_roadmap

    monkeypatch.setattr(profile_module, "PROFILE_DIR", tmp_path)

    profile = CareerProfile()
    profile.plan = parse_roadmap(jsonlib.dumps({
        "phases": [{
            "type": "intern", "name": "实习冲刺", "goal": "拿 offer",
            "jd_status": "has_jd",
            "jd": {"samples": [{
                "company": "某公司", "title": "Agent 实习", "salary": "500 元/天",
                "requirements": ["Python", "RAG"],
            }]},
            "milestones": [],
        }],
    }, ensure_ascii=False))
    profile.touch()

    html = render_roadmap_map(profile)

    assert "某公司 · Agent 实习（500 元/天）：Python；RAG" in html
    assert "samples：[" not in html
    assert "返回控制台" in html

    block = html.split('id="career-data">')[1].split("</script>")[0]
    data = jsonlib.loads(block)
    assert data["phases"][0]["is_current"] is True
    assert data["phases"][0]["type_label"] == "实习"


def test_roadmap_map_marks_baseline_and_execution(tmp_path, monkeypatch):
    """职业地图要能看出是基线方案，还是按确认企业/JD 校准过的执行版。"""
    import json as jsonlib

    import src.tools.profile as profile_module
    from src.models import CareerProfile
    from src.tools.dashboard import render_roadmap_map
    from src.tools.roadmap import parse_roadmap

    monkeypatch.setattr(profile_module, "PROFILE_DIR", tmp_path)

    profile = CareerProfile()
    profile.plan = parse_roadmap(jsonlib.dumps({
        "phases": [{"type": "learn", "name": "阶段一", "goal": "g",
                    "milestones": [{"name": "M", "tasks": [{"name": "任务甲"}]}]}],
    }, ensure_ascii=False))
    profile.touch()

    baseline = render_roadmap_map(profile)
    assert 'name="career-kit-plan-mode" content="baseline"' in baseline
    assert "基线版：尚未按目标企业 JD 校准" in baseline

    profile.core_state = {
        "stage": "executing",
        "requirement_profile_id": "rp_test",
        "execution_plan_id": "ep_test",
    }
    execution = render_roadmap_map(profile)
    assert 'name="career-kit-plan-mode" content="execution"' in execution
    assert "执行版：已按确认企业与 JD 需求校准" in execution
    assert "rp_test" in execution and "ep_test" in execution
