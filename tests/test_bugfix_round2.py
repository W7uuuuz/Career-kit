"""BUG 修复第二轮回归：审计落库/force 定稿/层级升级/lint/stale/投递删除/参数校验。

对应 dev/test/BUG.md 33 项中的代码修复面锁定：
- #7/#8/#9/#10  save_roadmap 先校验后落盘 + force 出口 + save_roadmap_audit 落库
- #4/#5         start_level_after 复评升级 + 合规 +1 放行
- #11           伞形任务/时间词 lint + KPI 计数闭合软提示
- #29           import_jd 后 gap 标记过期，get_workflow_status 强制重新分析
- #33           delete_application 删除投递记录
- #25           未知参数报错（loader 单点校验）
- #26           knowledge 相关度阈值
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

import pytest
import src.tools.profile as profile_module


@pytest.fixture()
def temp_profile(tmp_path, monkeypatch):
    """把档案指到临时目录；工具模块统一走 profile.load_profile。"""
    monkeypatch.setattr(profile_module, "PROFILE_DIR", tmp_path)
    return tmp_path


def _mk():
    """干净档案 + 三轴齐全（过 save_roadmap 的前置）。"""
    from src.server import intake

    intake("who", '{"name": "张三", "graduation_year": "2028"}')
    intake("have", '{"skills": ["Python"], "experience_level": "小厂"}')
    intake("want", '{"target_role": "AI 工程师"}')


def _valid_roadmap(**overrides):
    """可过硬校验的最小路线图（小厂 → intern 小厂 → project）。"""
    roadmap = {
        "roadmap": {
            "strategy_summary": "测试路线",
            "start_level": "小厂",
            "phases": [
                {
                    "type": "intern", "name": "小厂实习", "company": "某小厂",
                    "target_level": "小厂", "resume_value": "实习经历",
                    "kpi": {"metric": "入职", "target": "1个"},
                },
            ],
        }
    }
    if overrides:
        roadmap["roadmap"].update(overrides)
    return roadmap


# ============ #8 审计落库 ============


def test_save_roadmap_audit_roundtrip(temp_profile):
    from src.server import save_roadmap, save_roadmap_audit

    roadmap = _valid_roadmap()
    assert json.loads(save_roadmap_audit(json.dumps({"verdict": "PASS"}))).get("isError") is True, (
        "无路线图时审计应拒绝"
    )

    out = json.loads(save_roadmap(json.dumps(roadmap, ensure_ascii=False), force=True))
    assert out["context"]["phase"] == "roadmap_saved"

    # FAIL 无 issues 明细 → 拒绝
    fail_no_issues = json.loads(save_roadmap_audit(json.dumps({"verdict": "FAIL"})))
    assert fail_no_issues["code"] == "INVALID_PARAM"

    # 正常 FAIL 落库 → 尚未复审计时 save_roadmap 被审计状态卡住
    audit = json.loads(save_roadmap_audit(json.dumps({
        "verdict": "FAIL",
        "issues": [{"checklist_id": "quantifiable", "problem": "KPI 模糊", "fix": "补数字"}],
        "summary": "1 项待修",
    })))
    assert audit["context"]["verdict"] == "FAIL" and audit["context"]["fail_rounds"] == 1

    blocked = json.loads(save_roadmap(json.dumps(roadmap, ensure_ascii=False)))
    assert blocked.get("isError") is True
    assert blocked["code"] == "VALIDATION_FAILED"
    assert "verdict=FAIL" in blocked["message"]

    # PASS 落库后放行
    audit2 = json.loads(save_roadmap_audit(json.dumps({"verdict": "PASS", "summary": "通过"})))
    assert audit2["context"]["verdict"] == "PASS"
    ok = json.loads(save_roadmap(json.dumps(roadmap, ensure_ascii=False)))
    assert ok["context"]["phase"] == "roadmap_saved"

    # 非法 verdict → 拒绝
    bad = json.loads(save_roadmap_audit(json.dumps({"verdict": "MAYBE"})))
    assert bad["code"] == "INVALID_PARAM"


def test_audit_two_fail_rounds_offers_force_exit(temp_profile):
    """#9：两轮 FAIL 后给出「修正 / force 定稿」双出口，不再无限重审。"""
    from src.server import save_roadmap, save_roadmap_audit

    save_roadmap(json.dumps(_valid_roadmap(), ensure_ascii=False), force=True)
    save_roadmap_audit(json.dumps({"verdict": "FAIL", "issues": [
        {"checklist_id": "quantifiable", "problem": "p1", "fix": "f1"},
    ]}))
    out = json.loads(save_roadmap_audit(json.dumps({"verdict": "FAIL", "issues": [
        {"checklist_id": "start_alignment", "problem": "p2", "fix": "f2"},
    ]})))
    assert out["context"]["fail_rounds"] == 2
    assert "force=true" in out["message"] or "force" in out["message"]
    assert "带问题定稿" in out["message"]

    # force=true 定稿时审计风险在 message 中被复述
    saved = json.loads(save_roadmap(json.dumps(_valid_roadmap(), ensure_ascii=False), force=True))
    assert "verdict=FAIL" in saved["message"], "带问题定稿必须显式复述风险"
    assert saved["context"]["accepted_risks"], "风险应有结构化记录"


# ============ #4/#5 层级模型 ============


def test_compliant_plusone_allowed(temp_profile):
    """#5：intern 目标 = 起点+1 直接放行（不再报「高于起点」）。"""
    from src.server import save_roadmap

    _mk()
    roadmap = {
        "roadmap": {
            "strategy_summary": "合规爬升",
            "start_level": "小厂",
            "phases": [
                {"type": "intern", "name": "中厂实习", "target_level": "中厂",
                 "resume_value": "实习经历", "kpi": {"metric": "入职", "target": "1个"}},
            ],
        }
    }
    out = json.loads(save_roadmap(json.dumps(roadmap, ensure_ascii=False)))
    assert out["context"]["phase"] == "roadmap_saved"
    assert out["context"]["accepted_risks"] == []


def test_start_level_after_enables_staged_climb(temp_profile):
    """#4：复评升级合法（learn 复评升中厂 → 中厂 intern），并同步更新档案起点。"""
    from src.server import save_roadmap
    from src.tools import profile as profile_module

    roadmap = {
        "roadmap": {
            "strategy_summary": "分阶段爬升",
            "start_level": "小厂",
            "phases": [
                {
                    "type": "learn", "name": "基础学习",
                    "kpi": {"metric": "完成第 1 章练习 3 道", "target": "3道"},
                    "start_level_after": "中厂",
                },
                {
                    "type": "intern", "name": "中厂实习", "target_level": "中厂",
                    "resume_value": "实习经历", "kpi": {"metric": "入职", "target": "1个"},
                },
            ],
        }
    }
    out = json.loads(save_roadmap(json.dumps(roadmap, ensure_ascii=False)))
    assert out["context"]["phase"] == "roadmap_saved"
    assert out["context"]["accepted_risks"] == []
    assert any("start_level_after" in s for s in out["context"]["soft_reports"])

    p = profile_module.load_profile()
    assert (p.gap or {}).get("start_level") == "中厂", "复评升级应写回档案起点"

    # 同一路线但删掉 start_level_after：小厂 → 中厂是 +1 合规；再放大厂应被拦
    climb_check = {"roadmap": dict(roadmap["roadmap"])}
    climb_check["roadmap"]["phases"] = [
        {"type": "intern", "name": "大厂实习", "target_level": "大厂",
         "resume_value": "实习经历", "kpi": {"metric": "入职", "target": "1个"}},
    ]
    blocked = json.loads(save_roadmap(json.dumps(climb_check, ensure_ascii=False)))
    assert blocked.get("isError") is True


# ============ #11 roadmap lint ============


def test_roadmap_lint_rejects_umbrella_and_time_words(temp_profile):
    from src.server import save_roadmap

    _mk()
    roadmap = {
        "roadmap": {
            "strategy_summary": "lint 测试",
            "start_level": "小厂",
            "phases": [
                {
                    "type": "learn", "name": "刷题阶段",
                    "kpi": {"metric": "每周刷题数量", "target": "100道"},
                    "milestones": [
                        {"name": "专题一", "tasks": [
                            {"name": "按五类专题刷题"},
                            {"name": "每日复习错题"},
                        ]},
                    ],
                },
            ],
        }
    }
    out = json.loads(save_roadmap(json.dumps(roadmap, ensure_ascii=False)))
    assert out.get("isError") is True
    assert out["code"] == "VALIDATION_FAILED"
    assert "伞形" in out["message"] and "时间词" in out["message"]


def test_kpi_without_counted_tasks_via_soft_report(temp_profile):
    """量化 KPI 与任务计数不闭合 → 软提示（不拒绝保存）。"""
    from src.server import save_roadmap

    _mk()
    roadmap = {
        "roadmap": {
            "strategy_summary": "计数闭合",
            "start_level": "小厂",
            "phases": [
                {
                    "type": "learn", "name": "刷题阶段",
                    "kpi": {"metric": "完成题量", "target": "150道"},
                    "milestones": [
                        {"name": "M1", "tasks": [{"name": "刷题"}]},  # 无计数
                    ],
                },
            ],
        }
    }
    out = json.loads(save_roadmap(json.dumps(roadmap, ensure_ascii=False)))
    assert out["context"]["phase"] == "roadmap_saved"
    assert any("计数" in s for s in out["context"]["soft_reports"])


# ============ #29 换 JD 后 gap 过期 ============


def test_import_jd_marks_gap_stale(temp_profile):
    from src.server import get_workflow_status, import_jd, save_gap_analysis
    from src.tools import profile as profile_module

    _mk()
    save_gap_analysis(json.dumps({
        "match_score": 62, "match_level": "partial_match", "start_level": "小厂",
        "skill_gaps": [{"skill": "TypeScript", "priority": "high", "current_level": "无",
                        "required_level": "熟练", "how_to_improve": "学习", "source": "测试"}],
    }, ensure_ascii=False))

    # 换 JD 前：状态指向 generate_roadmap（phase=planning）
    assert "generate_roadmap" in get_workflow_status()

    out = import_jd(json.dumps({
        "role": "新目标", "company": "某新厂",
        "requirements": ["Python"], "responsibilities": ["干活"],
    }, ensure_ascii=False))
    assert "标记为过期" in out and "analyze_gaps" in out, "import_jd 必须提示旧分析已过期"

    p = profile_module.load_profile()
    assert p.gap_stale_at, "import_jd 后旧分析必须标记过期"

    # 换 JD 后：workflow status 强制重新分析（不被旧 gap 骗到 generate_roadmap）
    # 注意：status 全文含完整菜单（介绍全流程会提到 generate_roadmap），
    # 判定点是「下一步」行必须指向 analyze_gaps
    status = get_workflow_status()
    assert "analyze_gaps" in status
    assert "重新分析" in status or "过期" in status
    next_step_row = [ln for ln in status.splitlines() if ln.startswith("**下一步**")]
    assert next_step_row, "状态应显式给出下一步"
    assert "analyze_gaps" in next_step_row[0] and "过期" in next_step_row[0]


# ============ #33 delete_application ============


def test_delete_application_roundtrip(temp_profile):
    from src.server import delete_application, record_application

    _mk()
    rec = json.loads(record_application(company="ACME", role="AI 工程师", status="applied"))
    app_id = rec["next_app_id_hint"]
    assert app_id

    out = json.loads(delete_application(application_id=app_id))
    assert "已删除投递记录：ACME" in out["message"]

    again = json.loads(delete_application(application_id=app_id))
    assert again["code"] == "MISSING_DATA"

    empty = json.loads(delete_application(application_id=""))
    assert empty["code"] == "INVALID_PARAM"


# ============ #25 未知参数 / #26 阈值 ============


def test_search_company_jobs_rejects_unknown_params(temp_profile):
    from src.scrapers import search_company_jobs

    result = search_company_jobs("bytedance", keyword="AI", foo="bar")
    assert result.get("error")
    assert "foo" in result["error"]


def test_search_knowledge_drops_weak_hits(temp_profile):
    from src.tools import knowledge_search as ks

    m = pytest.MonkeyPatch()
    m.setattr(ks, "KNOWLEDGE_DIR", pytest.importorskip("pathlib").Path(
        ks.KNOWLEDGE_DIR
    ))  # 占位：真实目录不写盘，低分截断逻辑在 data_tools 层已有弱相关提示
    m.undo()
    # 直接验证阈值常量与函数行为的契约
    assert ks.MIN_RELEVANCE > 1
    res = ks.search_knowledge("完全无关不存在的词组合xyz123abstract")
    for r in res["results"]:
        assert r["relevance"] >= ks.MIN_RELEVANCE
