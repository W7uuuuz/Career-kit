"""执行 playbook 回归：任务怎么做 / 资源链接 / 完成标准。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

import src.tools.profile as profile_module  # noqa: E402
from src.models import CareerProfile  # noqa: E402
from src.tools.resource_catalog import (  # noqa: E402
    load_catalog,
    select_resources,
    validate_resources,
)


@pytest.fixture()
def temp_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(profile_module, "PROFILE_DIR", tmp_path)
    return tmp_path


def _profile_with_roadmap() -> CareerProfile:
    profile = CareerProfile()
    profile.who = {"name": "张三"}
    profile.have = {"skills": ["Python"]}
    profile.summary = "应届生"
    profile.plan = {
        "roadmap": {
            "strategy_summary": "先补基础",
            "phases": [{
                "id": "phase_1",
                "name": "基础补齐",
                "type": "learn",
                "goal": "能手写常见模块",
                "milestones": [{
                    "id": "phase_1_ms_1",
                    "name": "算法基础",
                    "tasks": [{"name": "刷 LeetCode 热题 100"}],
                }],
            }],
        }
    }
    return profile


def _detail_payload() -> dict:
    return {
        "phase_id": "phase_1",
        "tasks": [{
            "name": "LeetCode 热题 100：数组与字符串 5 题",
            "description": "按题号顺序做，先想再写",
            "how_to": ["先想 10 分钟", "再写代码", "错题隔天重做"],
            "resources": [{
                "label": "LeetCode 热题 100",
                "url": "https://leetcode.cn/problem-list/2cktkvj/",
            }],
            "done_criteria": "独立写出 5 题并通过，错题已记录",
            "priority": "high",
            "checkin_mode": "daily",
            "checkin_goal": 5,
        }],
    }


def test_resource_catalog_has_known_links():
    catalog = load_catalog()

    assert catalog, "sop/resources.yaml 未加载"
    urls = {item["url"] for item in catalog}
    assert "https://leetcode.cn/problem-list/2cktkvj/" in urls

    algorithm = select_resources(["algorithm"], limit=5)
    assert any(item["id"] == "leetcode-hot-100" for item in algorithm)


def test_validate_resources_flags_unknown_and_allows_search():
    known = validate_resources([{
        "label": "LeetCode 热题 100",
        "url": "https://leetcode.cn/problem-list/2cktkvj/",
    }])
    assert known == []

    unknown = validate_resources([{"label": "某网站", "url": "https://example.com/x"}])
    assert any("不在资源目录" in w for w in unknown)

    search_only = validate_resources([{"label": "XX 官方文档", "search": "XX 文档"}])
    assert search_only == []


def test_save_detail_and_generate_tasks_keep_playbook(temp_profile):
    from src.server import generate_tasks, save_current_detail

    profile_module.save_profile(_profile_with_roadmap())

    saved = json.loads(save_current_detail(json.dumps(_detail_payload(), ensure_ascii=False)))
    assert saved["context"]["task_count"] == 1
    assert saved["context"]["advisories"] == []

    generate_tasks()
    task = profile_module.load_profile().tasks[0]

    assert task.how_to == ["先想 10 分钟", "再写代码", "错题隔天重做"]
    assert task.resources[0]["url"] == "https://leetcode.cn/problem-list/2cktkvj/"
    assert task.done_criteria == "独立写出 5 题并通过，错题已记录"
    assert task.checkin_mode == "daily" and task.checkin_goal == 5


def test_save_detail_reports_missing_playbook(temp_profile):
    from src.server import save_current_detail

    profile_module.save_profile(_profile_with_roadmap())
    result = json.loads(save_current_detail(json.dumps({
        "phase_id": "phase_1",
        "tasks": [{"name": "只有标题的任务", "priority": "high"}],
    }, ensure_ascii=False)))

    advisories = " ".join(result["context"]["advisories"])
    assert "how_to" in advisories
    assert "done_criteria" in advisories


def test_detail_current_phase_exposes_resource_catalog(temp_profile):
    from src.server import detail_current_phase, generate_tasks, save_current_detail

    profile_module.save_profile(_profile_with_roadmap())
    save_current_detail(json.dumps(_detail_payload(), ensure_ascii=False))
    generate_tasks()

    detail = json.loads(detail_current_phase())
    assert detail["resource_catalog"]
    assert any(item["id"] == "leetcode-hot-100" for item in detail["resource_catalog"])
    assert "how_to" in detail["instructions"]


def test_dashboard_shows_milestone_preview_without_tasks(temp_profile):
    from src.tools.dashboard import render_roadmap_map

    profile_module.save_profile(_profile_with_roadmap())
    html = render_roadmap_map(profile_module.load_profile())

    assert "里程碑已规划" in html
    assert "刷 LeetCode 热题 100" in html


def test_dashboard_renders_task_playbook(temp_profile):
    from src.server import generate_tasks, save_current_detail
    from src.tools.dashboard import render_roadmap_map

    profile_module.save_profile(_profile_with_roadmap())
    save_current_detail(json.dumps(_detail_payload(), ensure_ascii=False))
    generate_tasks()

    html = render_roadmap_map(profile_module.load_profile())

    assert "先想 10 分钟" in html
    assert "https://leetcode.cn/problem-list/2cktkvj/" in html
    assert "独立写出 5 题并通过" in html
    assert "怎么做 / 完成标准" in html
