"""质量建议化后的回归：审计持久化、层级建议、数据口径、未知字段与响应体积。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

import pytest
import src.tools.profile as profile_module
from src.research_digest import build_digest, render_digest_lines


@pytest.fixture()
def temp_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(profile_module, "PROFILE_DIR", tmp_path)
    monkeypatch.setenv("CAREER_KIT_ASSETS_DIR", str(tmp_path / "CareerKit"))
    return tmp_path


def _mk_profile():
    from src.server import intake

    intake("who", '{"name": "张三", "graduation_year": "2028"}')
    intake("have", '{"skills": ["Python"], "experience_level": "小厂"}')
    intake("want", '{"target_role": "AI 工程师"}')


# ============ 数据口径 ============


def test_salary_uses_lower_upper_and_midpoint():
    digest = build_digest([
        {"title": "A", "salary": "40-70K·15薪"},
        {"title": "B", "salary": "20-30K"},
        {"title": "C", "salary": "面议"},
    ], [])
    salary = digest["salary"]
    assert salary["count"] == 2
    assert salary["min_k"] == 20
    assert salary["max_k"] == 70
    assert salary["median_k"] == 40.0  # 中点 55 与 25 的中位数


def test_city_normalization_primary_distribution():
    digest = build_digest([
        {"title": "A", "location": "上海"},
        {"title": "B", "location": "上海市"},
        {"title": "C", "location": "徐汇区"},
        {"title": "D", "location": "上海 / 北京"},
    ], [])
    assert digest["cities"] == [{"city": "上海", "count": 4}]
    assert digest["multi_city_jd_count"] == 1
    lines = render_digest_lines(digest)
    assert any("主城市" in line for line in lines)


def test_education_mentions_use_requirements_section():
    digest = build_digest([
        {"title": "A", "description": "团队本科以上，氛围好",
         "requirements": "硕士及以上学历"},
        {"title": "B", "description": "本科团队", "requirements": "双非友好"},
    ], [])
    edu = digest["education_mentions"]
    assert edu.get("硕士") == 1
    assert edu.get("双非") == 1
    assert edu.get("本科", 0) == 0, "公司介绍里的学历词不应计入要求"


def test_case_counts_expose_raw_and_filtered():
    from src.research_report import build_report

    profile = profile_module.load_profile()
    url = "https://example.com/j/1"
    report = build_report(profile, {
        "direction": "AI",
        "jd_families": [{
            "slug": "b", "label": "B", "status": "ok", "error": "", "elapsed": 0,
            "rows": [{"title": "岗位", "url": url, "description": "描述",
                      "requirements": "要求", "company": "B"}],
        }],
        "cases_result": {
            "cases": [
                {"kind": "interview_requirements", "title": "同名岗位", "url": url,
                 "origin": "local_jd", "source": "local", "background": {}},
                {"kind": "success_experience", "title": "上岸复盘", "url": "u2",
                 "source": "nowcoder", "background": {}, "highlights": ["a"]},
            ],
            "warnings": [], "sources": {"local": 1, "nowcoder": 1},
        },
    })
    assert report["counts"]["cases"] == 1
    assert report["counts"]["cases_raw"] == 2
    assert report["counts"]["cases_filtered"] == 1
    assert report["digest"]["case_count_raw"] == 2


# ============ 审计持久化 ============


def _roadmap(title="实习"):
    return {"roadmap": {"strategy_summary": "测试", "start_level": "小厂", "phases": [
        {"type": "intern", "name": title, "company": "某厂", "target_level": "小厂",
         "resume_value": "实习", "kpi": {"metric": "入职", "target": "1个"}},
    ]}}


def test_audit_survives_save_and_marks_stale_on_change(temp_profile):
    from src.server import save_roadmap, save_roadmap_audit

    _mk_profile()
    save_roadmap(json.dumps(_roadmap(), ensure_ascii=False))
    save_roadmap_audit(json.dumps({"verdict": "FAIL", "issues": [
        {"checklist_id": "quantifiable", "problem": "KPI 模糊", "fix": "补数字"},
    ]}))
    saved = json.loads(save_roadmap(json.dumps(_roadmap(), ensure_ascii=False)))
    profile = profile_module.load_profile()
    assert profile.audit["latest_verdict"] == "FAIL", "审计记录不得被 save_roadmap 清空"
    assert saved["context"]["audit"]["stale"] is False

    changed = json.loads(save_roadmap(json.dumps(_roadmap("另一段实习"), ensure_ascii=False)))
    profile = profile_module.load_profile()
    assert profile.audit["stale"] is True, "路线图内容变化后审计应标记过期"
    assert changed["context"]["audit"]["stale"] is True


# ============ 层级建议 ============


def test_start_level_after_cannot_bootstrap_same_phase(temp_profile):
    from src.server import save_roadmap

    _mk_profile()
    roadmap = {"roadmap": {"start_level": "小厂", "phases": [
        {"type": "intern", "name": "大厂实习", "target_level": "大厂",
         "start_level_after": "大厂", "resume_value": "实习",
         "kpi": {"metric": "入职", "target": "1个"}},
    ]}}
    out = json.loads(save_roadmap(json.dumps(roadmap, ensure_ascii=False)))
    codes = [a["code"] for a in out["context"]["advisories"]]
    assert "level_jump" in codes, "同阶段 start_level_after 不得绕过跨级提示"


def test_unknown_level_and_graduation_are_advisories(temp_profile):
    from src.server import save_roadmap

    _mk_profile()
    roadmap = {"roadmap": {"start_level": "中大厂", "phases": [
        {"type": "intern", "name": "实习", "target_level": "神秘厂",
         "graduation_year": "2029", "resume_value": "实习",
         "kpi": {"metric": "入职", "target": "1个"}},
    ]}}
    out = json.loads(save_roadmap(json.dumps(roadmap, ensure_ascii=False)))
    codes = {a["code"] for a in out["context"]["advisories"]}
    assert "unknown_start_level" in codes
    assert "unknown_target_level" in codes
    assert "graduation_mismatch" in codes


# ============ 差距分析未知字段 / 响应瘦身 ============


def test_gap_unknown_fields_are_reported(temp_profile):
    from src.server import save_gap_analysis

    out = json.loads(save_gap_analysis(json.dumps({
        "match_score": 60,
        "skill_gaps": [{"skill": "RAG", "source": "JD"}],
        "experience_2": {"experience": "被误写进嵌套字段"},
    }, ensure_ascii=False)))
    assert any(a["code"] == "unknown_fields" for a in out["context"]["advisories"])
    assert "experience_2" in out["message"]


def test_generate_roadmap_response_is_compacted(temp_profile):
    from src.server import generate_roadmap, save_gap_analysis

    _mk_profile()
    save_gap_analysis(json.dumps({
        "match_score": 60,
        "skill_gaps": [{"skill": "RAG", "source": "JD"}],
    }, ensure_ascii=False))
    out = json.loads(generate_roadmap())
    methodology = out["methodology"]
    assert "audit_checklist" not in methodology, "生成阶段不必重复下发审计清单"
    assert all("data_needs" not in phase for phase in methodology.get("phases", []))
    assert len(json.dumps(out, ensure_ascii=False)) < 16000
