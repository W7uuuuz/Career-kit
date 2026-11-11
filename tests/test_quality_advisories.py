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

    from conftest import promote_profile

    intake("who", '{"name": "张三", "graduation_year": "2028"}')
    intake("have", '{"skills": ["Python"], "experience_level": "小厂"}')
    intake("want", '{"target_role": "AI 工程师"}')
    promote_profile(profile_module.load_profile())


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
    assert report["counts"]["cases_raw"] == 1
    assert report["counts"]["cases_filtered"] == 0
    assert report["counts"]["jd_from_cases"] == 1, "本地 JD 不计入案例数"
    assert report["digest"]["case_count_raw"] == 1


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


def test_graduation_mismatch_prompt_is_visible_and_non_blocking(temp_profile):
    from src.server import save_roadmap

    _mk_profile()  # who.graduation_year = 2028
    roadmap = {"roadmap": {"start_level": "小厂", "phases": [
        {"type": "intern", "name": "实习", "target_level": "小厂",
         "graduation_year": "2029", "resume_value": "实习",
         "kpi": {"metric": "入职", "target": "1个"}},
    ]}}
    out = json.loads(save_roadmap(json.dumps(roadmap, ensure_ascii=False)))
    assert not out.get("isError")
    codes = {a["code"] for a in out["context"]["advisories"]}
    assert "graduation_mismatch" in codes
    assert "2029" in out["message"] and "2028" in out["message"]
    assert "不一致" in out["message"]
    assert "自动抓取" in out["message"]


def test_three_and_five_phase_roadmaps_save_without_forced_four(temp_profile):
    from src.server import save_roadmap

    _mk_profile()

    def _roadmap(count: int) -> dict:
        phases = [
            {
                "type": "learn" if index == 0 else "project",
                "name": f"阶段{index + 1}",
                "goal": "阶段目标",
                "resume_value": "" if index == 0 else "可写进简历的产出",
                "kpi": {"metric": "产出", "target": "1个"},
            }
            for index in range(count)
        ]
        return {
            "roadmap": {
                "strategy_summary": "阶段数按差距决定",
                "start_level": "小厂",
                "phases": phases,
            }
        }

    for count in (3, 5):
        out = json.loads(save_roadmap(json.dumps(_roadmap(count), ensure_ascii=False)))
        assert not out.get("isError")
        assert out["context"]["phase"] == "roadmap_saved"
        assert "必须 4 段" not in out["message"]
        saved = profile_module.load_profile()
        assert len(saved.plan["roadmap"]["phases"]) == count


def test_pending_jd_prompt_mentions_auto_fetch(temp_profile):
    from src.server import save_roadmap

    _mk_profile()
    roadmap = {"roadmap": {"start_level": "小厂", "phases": [
        {"type": "intern", "name": "实习", "company": "某厂", "target_level": "小厂",
         "jd_status": "pending_user_import", "graduation_year": "2028",
         "resume_value": "实习", "kpi": {"metric": "入职", "target": "1个"}},
    ]}}
    out = json.loads(save_roadmap(json.dumps(roadmap, ensure_ascii=False)))
    assert not out.get("isError")
    assert "后续自动抓取" in out["message"]
    assert "import_jd" in out["message"]



# ============ 差距分析未知字段 / 响应瘦身 ============


def test_gap_unknown_fields_are_reported(temp_profile):
    from src.server import save_gap_analysis

    from conftest import promote_profile

    promote_profile(profile_module.load_profile())
    out = json.loads(save_gap_analysis(json.dumps({
        "match_score": 60,
        "skill_gaps": [{"skill": "RAG", "source": "JD"}],
        "experience_2": {"experience": "自己写的额外字段"},
    }, ensure_ascii=False)))
    assert any(a["code"] == "unknown_fields" for a in out["context"]["advisories"])
    assert "experience_2" in out["message"]


def test_gap_advisories_persist_to_profile(temp_profile):
    from src.server import save_gap_analysis

    from conftest import promote_profile

    promote_profile(profile_module.load_profile())
    out = json.loads(save_gap_analysis(json.dumps({
        "match_score": 60,
        "skill_gaps": [],
    }, ensure_ascii=False)))
    assert not out.get("isError"), out
    profile = profile_module.load_profile()
    stored = profile.advisories["gap"]
    assert stored["items"], "差距建议应持久化到档案"
    assert stored["updated_at"]
    assert [a["code"] for a in stored["items"]] == [
        a["code"] for a in out["context"]["advisories"]
    ]


def test_roadmap_advisories_persist_and_clear(temp_profile):
    from src.server import save_roadmap

    _mk_profile()
    with_advisory = {"roadmap": {"start_level": "小厂", "phases": [
        {"type": "project", "name": "做项目", "kpi": {"metric": "完成", "target": "1个"}},
    ]}}
    out = json.loads(save_roadmap(json.dumps(with_advisory, ensure_ascii=False)))
    assert any(a["code"] == "missing_resume_value" for a in out["context"]["advisories"])
    profile = profile_module.load_profile()
    assert profile.advisories["roadmap"]["items"], "路线图建议应持久化到档案"
    assert profile.advisories["roadmap"]["updated_at"]

    clean = {"roadmap": {"start_level": "小厂", "phases": [
        {"type": "learn", "name": "基础学习", "kpi": {"metric": "完成", "target": "1个"}},
    ]}}
    out = json.loads(save_roadmap(json.dumps(clean, ensure_ascii=False)))
    assert out["context"]["advisories"] == []
    profile = profile_module.load_profile()
    assert profile.advisories["roadmap"]["items"] == [], "新路线图无建议时应清空旧建议"


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
    assert "evidence" in out and "required_evidence" in out
    assert {item["id"] for item in out["required_evidence"]} == {
        "channel", "conversion", "threshold", "timeline",
    }


# ============ 通道现实与引用 ============


def _record_claim(**overrides):
    from src.server import record_claim

    payload = {
        "statement": "双非进大厂常见多段大厂实习，每段约 6 个月",
        "claim_type": "practitioner_experience",
        "source": {"type": "practitioner", "name": "阿里 HR", "date": "2026-11-11"},
        "scope": {"education": "双非本", "channel": "校招"},
        "limitation": "单一口述，未做统计",
    }
    payload.update(overrides)
    return json.loads(record_claim(json.dumps(payload, ensure_ascii=False)))


def _channel_roadmap(**phase_overrides):
    phase = {
        "type": "intern",
        "name": "大厂实习",
        "target_level": "大厂",
        "resume_value": "大厂实习经历",
        "kpi": {"metric": "入职", "target": "1个"},
        "access_paths": [{"channel": "暑期实习", "rationale": "主要通道"}],
        "rationale": "双非需要三段大厂实习，每段 6 个月",
    }
    phase.update(phase_overrides)
    return {"roadmap": {"start_level": "小厂", "phases": [phase]}}


def _codes(out: dict) -> set[str]:
    return {item["code"] for item in out["context"]["advisories"]}


def test_single_channel_and_missing_window_are_advisories(temp_profile):
    from src.server import save_roadmap

    _mk_profile()
    out = json.loads(save_roadmap(json.dumps(_channel_roadmap(), ensure_ascii=False)))
    codes = _codes(out)
    assert "single_channel" in codes
    assert "no_fallback" in codes
    assert "missing_time_window" in codes
    assert "numeric_claim_unsourced" in codes


def test_conversion_risk_and_unknown_claim_are_advisories(temp_profile):
    from src.server import save_roadmap

    _mk_profile()
    out = json.loads(save_roadmap(json.dumps(_channel_roadmap(
        access_paths=[
            {"channel": "暑期实习", "rationale": "主通道"},
            {"channel": "实习转正", "rationale": "留用"},
        ],
        claims=["cl_999"],
    ), ensure_ascii=False)))
    codes = _codes(out)
    assert "conversion_unflagged" in codes
    assert "claim_unknown" in codes


def test_cited_channel_roadmap_is_clean(temp_profile):
    from src.server import save_roadmap

    _mk_profile()
    claim = _record_claim()
    assert claim["claim"]["id"] == "cl_001"

    out = json.loads(save_roadmap(json.dumps(_channel_roadmap(
        access_paths=[
            {"channel": "暑期实习", "rationale": "主通道", "evidence_ids": ["cl_001"]},
            {"channel": "秋招提前批", "rationale": "并行通道"},
        ],
        fallback_paths=[{"channel": "中厂正式批", "rationale": "保底"}],
        conversion_risk={"level": "中", "reason": "HC 受部门影响", "evidence_ids": ["cl_001"]},
        time_window={"window": "秋招提前批 7-8 月", "deadline": "2027-08-31"},
        decision_gate={"condition": "暑期实习未 offer", "action": "转提前批 + 中厂保底"},
        claims=["cl_001"],
    ), ensure_ascii=False)))
    codes = _codes(out)
    for code in (
        "single_channel",
        "no_fallback",
        "conversion_unflagged",
        "missing_time_window",
        "claim_missing",
        "numeric_claim_unsourced",
        "claim_unknown",
    ):
        assert code not in codes, f"干净的通道路线图不应命中 {code}"


def test_stale_claim_is_advisory(temp_profile):
    from src.server import save_roadmap

    _mk_profile()
    claim = _record_claim(expires_at="2000-01-01")
    out = json.loads(save_roadmap(json.dumps(_channel_roadmap(
        access_paths=[
            {"channel": "暑期实习", "rationale": "主通道"},
            {"channel": "秋招提前批", "rationale": "并行通道"},
        ],
        fallback_paths=[{"channel": "中厂正式批", "rationale": "保底"}],
        time_window={"window": "秋招提前批"},
        claims=[claim["claim"]["id"]],
    ), ensure_ascii=False)))
    assert "claim_stale" in _codes(out)
