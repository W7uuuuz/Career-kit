"""MCP 工具函数级冒烟测试。

直接调用 server.py 的工具函数（不经 MCP 传输层），
用「docstring 官方 Schema」作为入参契约做回归：
BUG-004（save_gap_analysis schema 崩溃）、BUG-005（apply_insight 幽灵 import）
均由本层测试锁定。
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


def _parse(result_json: str) -> dict:
    data = json.loads(result_json)
    assert isinstance(data, dict)
    assert not data.get("isError"), f"工具返回错误: {data}"
    return data


def test_save_gap_analysis_accepts_docstring_minimal_schema(temp_profile):
    """BUG-004 回归：按 docstring 最小结构传参必须成功且不留半成品。"""
    from src.server import save_gap_analysis

    minimal = json.dumps({
        "match_score": 65,
        "skill_gaps": [
            {"skill": "LLM", "priority": "high",
             "current_level": "无", "required_level": "熟练", "source": "JD"}
        ],
        "priority_actions": ["学习基础"],
        "strengths": ["有项目经验"],
    }, ensure_ascii=False)

    result = _parse(save_gap_analysis(gap_json=minimal))
    assert result["context"]["phase"] == "gap_saved"
    assert "已保存" in result["message"]

    profile = profile_module.load_profile()
    assert profile.gap["match_score"] == 65
    assert not profile.journey or profile.journey[-1].phase == "analysis"


def test_save_gap_analysis_tolerates_string_entries(temp_profile):
    """字符串条目（LLM 退化输出）不崩，报告原样渲染。"""
    from src.server import save_gap_analysis

    degraded = json.dumps({
        "match_score": 50,
        "skill_gaps": [{"skill": "RAG", "priority": "medium",
                        "current_level": "无", "target_level": "熟练", "source": "JD"}],
        "priority_actions": ["先学检索基础"],
        "strengths": ["后端经验丰富"],
    }, ensure_ascii=False)

    result = _parse(save_gap_analysis(gap_json=degraded))
    assert "RAG" in result["message"]
    assert "后端经验丰富" in result["message"]
    assert "先学检索基础" in result["message"]


def test_save_gap_tolerates_malformed_values(temp_profile):
    """畸形字段值不抛异常：要么正常降级保存，要么返回标准错误，档案状态一致。"""
    from src.server import save_gap_analysis

    bad = json.dumps({"match_score": "not-a-number", "skill_gaps": [{"unexpected": 1}]})
    result = json.loads(save_gap_analysis(gap_json=bad))
    profile = profile_module.load_profile()

    if result.get("isError"):
        assert not profile.gap
    else:
        # 降级渲染后正常落盘，报告可读
        assert "not-a-number" in result["message"]


def test_intake_rejects_invalid_json(temp_profile):
    """BUG-007 回归：非法 JSON 必须返回结构化错误且不写档案。"""
    from src.server import intake

    result = json.loads(intake(section="who", data="{oops 非法JSON"))
    assert result.get("isError") is True
    assert result["code"] == "INVALID_JSON"

    profile = profile_module.load_profile()
    assert not profile.who, "坏输入不应写入档案"
    assert profile.version == 0


def test_import_plan_rejects_binary_garbage(temp_profile):
    """OBS-003 回归：控制字符垃圾内容返回结构化错误，不透传给 LLM。"""

    from src.server import import_plan

    garbage = temp_profile / "garbage.md"
    garbage.write_bytes(b"\x00\x01\x02binary junk \x1f\x03" * 50)

    result = json.loads(import_plan(file_path=str(garbage)))
    assert result.get("isError") is True
    assert "\x00" not in result["message"] and "\x01" not in result["message"]


def test_boss_login_navigates_and_zero_param():
    """BUG-009/OBS-004 回归：登录工具必须导航到 zhipin.com，且不接受参数拉起浏览器。"""
    login_src = (Path(__file__).parent.parent / "src" / "scrapers" / "boss" / "login.py").read_text(
        encoding="utf-8"
    )
    # 探针验证过 60 秒存活的 goto 必须存在于工具主流程（曾因丢失导致永久白屏）
    assert "page.goto(ZHIPIN_URL" in login_src
    # 带参即打印用法退出，绝不带参拉起浏览器
    assert "len(sys.argv) > 1" in login_src
    # 窗口尺寸由浏览器自适应用户屏幕：必须最大化、不得代码规定分辨率
    # （教训：硬编码小视口看不全，硬编码满屏分辨率又超出可视区）
    assert "--start-maximized" in login_src
    assert "--window-size=" not in login_src
    assert "viewport={" not in login_src  # 允许 no_viewport=True，禁止显式视口尺寸


def test_nowcoder_playwright_cleanup_in_finally():
    """nowcoder 爬虫的浏览器清理必须在 finally 中（曾因在 try 内导致异常路径泄漏进程）。"""
    src = (Path(__file__).parent.parent / "src" / "scrapers" / "nowcoder" / "scraper.py").read_text(
        encoding="utf-8"
    )
    assert "finally:" in src
    assert "browser.close()" in src
    assert "p.stop()" in src


def test_import_jd_rejects_empty_target(temp_profile):
    """BUG-010 回归：缺岗位业务字段的 JD 拒绝导入，不污染 target_jd。"""
    from src.server import import_jd

    result = json.loads(import_jd(jd_text='{"raw_text": "随便写点什么"}'))
    assert result.get("isError") is True
    assert result["code"] == "INVALID_JSON"
    assert not profile_module.load_profile().target_jd


def test_import_jd_rejects_blank_and_plaintext(temp_profile):
    """BUG-011 回归：空串/纯文本/非对象 JSON 一律拒绝，绝不静默 {"raw": text} 入库。"""
    from src.server import import_jd

    cases = ["", "   ", "随便写的文本不是JSON", "[]"]
    for bad in cases:
        result = json.loads(import_jd(jd_text=bad))
        assert result.get("isError") is True, f"输入 {bad!r} 应被拒绝"
        assert result["code"] == "INVALID_JSON", f"输入 {bad!r} 错误码不符"
    assert not profile_module.load_profile().target_jd

    # 合法结构化 JSON 仍可正常导入
    ok_text = import_jd(jd_text='{"company": "测试公司", "role": "AI 工程师"}')
    assert "已导入目标 JD" in ok_text
    assert profile_module.load_profile().target_jd["company"] == "测试公司"


def test_import_jd_file_no_copyable_example(temp_profile):
    """BUG-010 回归：import_jd_file 返回值不得包含可被直接复制的具体示例。"""
    from src.server import import_jd_file

    f = temp_profile / "jd.txt"
    f.write_text("负责 AI Agent 应用开发，熟悉 LangChain。", encoding="utf-8")

    text = import_jd_file(file_path=str(f))
    assert "禁止原样复制" in text
    assert '"role": "AI Agent 工程师"' not in text  # 具体示例值不应出现在返回值里


def test_workflow_status_goal_change_grading(temp_profile):
    """BUG-010 回归：want 变更强告警；target_jd 污染降级为可核查提示。"""
    from src.models import Task
    from src.server import get_workflow_status

    # target_jd 被示例污染（晚于路线图），但 want 未变 → 信息级提示而非重分析告警
    p = profile_module.load_profile()
    p.plan = {"roadmap": {"phases": [{"id": "phase_1", "name": "基础"}]}}
    p.plan_saved_at = "2026-08-26T10:00:00"
    p.section_updated_at = {"target_jd": "2026-08-26T11:00:00"}
    p.target_jd = {"company": "字节跳动", "role": "AI Agent 工程师", "requirements": ["LangGraph"]}
    p.tasks = [Task(id="task_001", name="任务", phase_id="phase_1")]
    profile_module.save_profile(p)

    st = get_workflow_status()
    assert "target_jd" in st and "误导入" in st
    assert "检测到用户目标（want）" not in st  # 不是重分析强告警

    # want 真实变更 → 强告警
    p.section_updated_at = {"want": "2026-08-26T12:00:00"}
    profile_module.save_profile(p)
    st2 = get_workflow_status()
    assert "检测到用户目标（want）" in st2 and "重新调用 analyze_gaps" in st2


def test_fetch_jd_detail_renders_interview_content(monkeypatch):
    """BUG-014 回归：面经详情必须渲染 content 字段，不能只有标题+公司。"""
    import asyncio

    import src.server as server_module

    fake = {
        "title": "字节跳动 火山引擎方舟一面面经",
        "company": "字节跳动",
        "content": "【精品面经】面试时长约 57 分钟……",
    }
    import src.tools.data_tools as data_tools

    monkeypatch.setattr(data_tools, "get_job_detail", lambda url, company=None: fake)

    out = asyncio.run(server_module.fetch_jd_detail("https://www.nowcoder.com/discuss/123"))
    assert "### 面经内容" in out
    assert "面试时长约 57 分钟" in out


def test_finalize_profile_probes_when_no_evidence(temp_profile):
    """BUG-015 + BUG-001 回归：have 有技能但无用户确认证据时，finalize 硬门禁阻塞不放行。"""
    from src.server import finalize_profile, intake

    intake("who", '{"name": "张三"}')
    intake("want", '{"target_role": "AI 工程师"}')
    intake("have", '{"skills": ["Python", "LangChain"], "experience": "2年"}')

    out = json.loads(finalize_profile())
    assert out.get("isError") is True
    assert out["code"] == "PROBING_REQUIRED"
    assert "user_verified" in out["message"]
    assert "authorship" in out["message"], "BUG-021：阻塞文案应含作者身份自评指引"

    # BUG-001 收紧：confidence 自标不算证据，仍需 user_verified，仍阻塞
    intake("have", '{"skill_evidence": [{"skill": "Python", "evidence": "爬虫项目", "confidence": "high"}]}')
    out2 = json.loads(finalize_profile())
    assert out2.get("isError") is True and out2["code"] == "PROBING_REQUIRED", \
        "confidence 自标不应豁免摸排"

    # 用户确认过的证据（user_verified=true）+ 自评三件套（BUG-021）才放行
    intake(
        "have",
        '{"core_skills": [{"skill": "Python", "evidence": "爬虫项目", "user_verified": true, '
        '"authorship": "self_written", "control_level": 5}], '
        '"self_assessment": {"resume_trust": "high", "notes": "均手写"}}',
    )
    out3 = finalize_profile()
    assert "档案已确认" in out3

    # 用户主动跳过（唯一合法绕过）——留痕 probe_skipped
    intake("have", '{"core_skills": [{"skill": "Python", "evidence": "爬虫项目"}]}')
    out4 = finalize_profile(skip_probing=True)
    assert "档案已确认" in out4
    assert profile_module.load_profile().probe_skipped is True


def test_finalize_probes_core_skills_without_evidence(temp_profile):
    """BUG-001 回归：教练写 core_skills 无证据时摸排硬门禁阻塞（字段名兼容）。"""
    from src.server import finalize_profile, intake

    intake("who", '{"name": "张三"}')
    intake("want", '{"target_role": "AI 工程师"}')
    intake("have", '{"core_skills": [{"skill": "LangGraph", "confidence": "高"}]}')

    out = json.loads(finalize_profile())
    assert out.get("isError") is True and out["code"] == "PROBING_REQUIRED", \
        "core_skills 无用户确认证据应阻塞摸排"


def test_analyze_gaps_blocked_without_probing(temp_profile):
    """BUG-001 双保险：技能无验证证据且未跳过时，analyze_gaps 拒绝分析。"""
    from src.server import analyze_gaps, finalize_profile, intake

    intake("who", '{"name": "张三"}')
    intake("want", '{"target_role": "AI 工程师"}')
    intake("have", '{"core_skills": [{"skill": "LangGraph", "confidence": "高"}]}')

    # finalize 未跳过 → analyze_gaps 也拒绝
    out = json.loads(analyze_gaps())
    assert out.get("isError") is True and out["code"] == "PROBING_REQUIRED"

    # 用户主动跳过摸排后 → 放行分析
    finalize_profile(skip_probing=True)
    out2 = analyze_gaps()
    assert "methodologies" in out2, "跳过摸排后应能分析"


def test_finalize_blocks_missing_authorship(temp_profile):
    """BUG-021 回归：证据齐全但缺 authorship/control_level/self_assessment 时阻塞。"""
    from src.server import finalize_profile, intake

    intake("who", '{"name": "张三"}')
    intake("want", '{"target_role": "AI 工程师"}')
    intake(
        "have",
        '{"core_skills": [{"skill": "LangGraph", "evidence": "项目实战", "user_verified": true}]}',
    )

    out = json.loads(finalize_profile())
    assert out.get("isError") is True and out["code"] == "PROBING_REQUIRED"
    assert "authorship" in out["message"]
    assert "AI" in out["message"], "阻塞文案应说明 AI 生成/验证形态需要用户自评"

    # 补齐自评三件套后放行
    intake(
        "have",
        '{"core_skills": [{"skill": "LangGraph", "evidence": "项目实战", "user_verified": true, '
        '"authorship": "ai_assisted", "control_level": 6}], '
        '"self_assessment": {"resume_trust": "medium", "notes": "LangGraph 为 AI 生成+人工验证"}}',
    )
    out2 = finalize_profile()
    assert "档案已确认" in out2
    assert profile_module.load_profile().probe_skipped is False


def test_finalize_authorship_skip_path_keeps_trace(temp_profile):
    """BUG-021：自评缺失时 skip_probing 是唯一旁路，且必须留痕。"""
    from src.server import finalize_profile, intake

    intake("who", '{"name": "张三"}')
    intake("have", '{"skills": ["Python"], "evidence": "多年实战（用户口头确认）"}')

    # 不带 skip → 阻塞（证据有了但整体自评缺失）
    out = json.loads(finalize_profile())
    assert out.get("isError") is True and out["code"] == "PROBING_REQUIRED"
    assert "self_assessment" in out["message"]

    # 用户明确要求跳过 → 放行 + 留痕
    out2 = finalize_profile(skip_probing=True)
    assert "档案已确认" in out2
    assert "已按用户要求跳过技能摸排" in out2
    assert profile_module.load_profile().probe_skipped is True


def test_analyze_gaps_blocks_late_skill_without_authorship(temp_profile):
    """BUG-021 双保险：finalize 后又录入缺自评的技能，analyze_gaps 拦截。"""
    from src.server import analyze_gaps, finalize_profile, intake

    intake("who", '{"name": "张三"}')
    intake("want", '{"target_role": "AI 工程师"}')
    intake(
        "have",
        '{"core_skills": [{"skill": "LangGraph", "evidence": "项目实战", "user_verified": true, '
        '"authorship": "ai_assisted", "control_level": 6}], '
        '"self_assessment": {"resume_trust": "medium", "notes": "AI 生成+验证"}}',
    )
    assert "档案已确认" in finalize_profile()

    # finalize 后又录了一个技能但没带自评（列表替换语义）
    intake("have", '{"core_skills": ["Docker"]}')
    out = json.loads(analyze_gaps())
    assert out.get("isError") is True and out["code"] == "PROBING_REQUIRED"
    assert "authorship" in out["message"]

    # 补齐后放行（core_skills 整体替换：两个技能都带自评）
    intake(
        "have",
        '{"core_skills": ['
        '{"skill": "Docker", "evidence": "部署实践", "user_verified": true, '
        '"authorship": "self_written", "control_level": 5}, '
        '{"skill": "LangGraph", "evidence": "项目实战", "user_verified": true, '
        '"authorship": "ai_assisted", "control_level": 6}]}',
    )
    out2 = analyze_gaps()
    assert "methodologies" in out2


def test_analyze_gaps_returns_step_template(temp_profile):
    """黑盒感修复回归：analyze_gaps 返回 4 步 step_template + 播报纪律 + 案例搜寻步。"""
    from src.server import analyze_gaps, finalize_profile, intake

    intake("who", '{"name": "张三"}')
    intake("want", '{"target_role": "AI 工程师"}')
    intake(
        "have",
        '{"core_skills": [{"skill": "LangGraph", "evidence": "项目实战", "user_verified": true, '
        '"authorship": "ai_assisted", "control_level": 6}], '
        '"self_assessment": {"resume_trust": "medium", "notes": "AI 生成+验证"}}',
    )
    finalize_profile()

    out = json.loads(analyze_gaps())

    steps = out["step_template"]
    assert len(steps) == 4
    assert [s["name"] for s in steps] == ["现状盘点", "案例搜寻", "两维分析", "结果预览与定稿"]
    assert [s["checkpoint"] for s in steps] == [True, False, False, True]

    case_step = steps[1]
    assert "search_cases" in case_step["action"], "案例搜寻必须点名独立工具"
    assert "不得用散抓 JD 替代" in case_step["action"]
    assert "cases_shown" in json.dumps(case_step["output"], ensure_ascii=False)

    # 分析步先讲方法论；结果预览步用户确认后才落盘
    assert "方法论" in steps[2]["action"]
    assert "用户确认" in steps[3]["action"]

    # 播报纪律：禁止静默连调工具 + 步骤预告（先报菜单再动手）
    assert "播报" in out["instructions"]
    assert "禁止静默连调工具" in out["instructions"]
    assert "步骤预告" in out["instructions"]
    assert "先向用户报完整菜单" in out["instructions"]


def test_search_cases_tool_renders_cases(temp_profile, monkeypatch):
    """search_cases：聚合层被打桩时不联网——返回案例卡文本 + 各源状态。"""
    import asyncio

    import src.tools.case_tools as ct
    from src.server import search_cases

    fake = {
        "cases": [
            {
                "kind": "success_experience",
                "title": "27届双非本 字节 offer 复盘",
                "source": "github",
                "url": "https://github.com/a/b/issues/1",
                "date": "2026-06-01",
                "background": {"education_tag": "双非本", "year": "27届", "company": "", "position": ""},
                "highlights": ["先小厂后大厂"],
                "match_score": 6.5,
            },
            {
                "kind": "interview_requirements",
                "title": "AI Agent 开发工程师",
                "source": "boss",
                "url": "https://zhipin.com/job/1",
                "date": "",
                "background": {"education_tag": "", "year": "", "company": "BOSS直聘", "position": ""},
                "highlights": ["熟悉 LangGraph/RAG"],
                "salary": "20-35K",
                "location": "深圳",
            },
        ],
        "warnings": ["nowcoder: Playwright 执行失败"],
        "sources": {"local": 0, "nowcoder": 0, "github": 1, "boss": 1},
    }
    monkeypatch.setattr(ct, "collect_cases", lambda *a, **k: fake)

    out = asyncio.run(search_cases(
        role="AI Agent 开发", education="双非本", company="字节"
    ))

    assert "同背景成功经验" in out and "面试要求" in out
    assert "27届双非本" in out
    assert "20-35K" in out
    assert "nowcoder: Playwright 执行失败" in out, "源失败必须如实上报"
    assert "不标注来源不诚实" in out

    # kind 过滤参数透传
    captured = {}

    def fake_collect(role, company, city, education, kind, limit):
        captured["kind"] = kind
        captured["limit"] = limit
        return {"cases": [], "warnings": [], "sources": {}}

    monkeypatch.setattr(ct, "collect_cases", fake_collect)
    out2 = asyncio.run(search_cases(role="后端", kind="requirements"))
    assert captured["kind"] == "requirements"
    assert "未命中" in out2 or "失败" in out2


def test_save_gap_ai_authorship_requires_red_flag(temp_profile):
    """BUG-021 质量门：AI 作者身份技能保存差距分析时必须有「AI 生成/手写」red flag。"""
    from src.server import intake, save_gap_analysis

    intake(
        "have",
        '{"core_skills": [{"skill": "LangGraph", "evidence": "项目实战", "user_verified": true, '
        '"authorship": "ai_generated", "control_level": 6}], '
        '"self_assessment": {"resume_trust": "medium", "notes": "AI 生成"}}',
    )

    bad = {
        "match_score": 70,
        "skill_gaps": [{"skill": "手写实现", "priority": "high", "source": "用户自评"}],
    }
    out = json.loads(save_gap_analysis(gap_json=json.dumps(bad, ensure_ascii=False)))
    assert out.get("isError") is True and out["code"] == "INCOMPLETE_ANALYSIS"
    assert "AI" in out["message"], "质量门应指出 AI 作者身份风险未显式暴露"

    good = dict(bad)
    good["resume_red_flags"] = [{
        "signal": "代码主要由 AI 生成，人工只做验证迭代",
        "risk": "面试被要求手写/逐行讲解时暴露",
        "evidence_fix": "补手写小项目与 PR 记录",
    }]
    out2 = json.loads(save_gap_analysis(gap_json=json.dumps(good, ensure_ascii=False)))
    assert out2.get("isError") is not True, out2
    assert "差距分析已保存" in out2.get("message", "")


def test_get_next_tasks_shows_full_overview(temp_profile):
    """BUG-016 回归：get_next_tasks 附带全流程概览（所有阶段+当前定位）。"""
    from src.models import Task
    from src.server import get_next_tasks

    p = profile_module.load_profile()
    p.plan = {"roadmap": {"phases": [
        {"id": "phase_1", "name": "基础巩固", "milestones": []},
        {"id": "phase_2", "name": "项目实战", "milestones": []},
    ]}}
    p.tasks = [
        Task(id="task_001", name="学Python", phase_id="phase_1", status="completed"),
        Task(id="task_002", name="学LangChain", phase_id="phase_1"),
        Task(id="task_003", name="做RAG项目", phase_id="phase_2"),
    ]
    profile_module.save_profile(p)

    out = get_next_tasks()
    assert "全流程" in out
    assert "基础巩固" in out and "项目实战" in out
    assert "[当前]" in out  # 当前阶段有定位标记


def test_roadmap_jd_fields_defaults():
    """jd 三件套默认字段：intern 未标注视为待导入占位，其余免 JD。"""
    from src.tools.roadmap import parse_roadmap

    roadmap = parse_roadmap(json.dumps({
        "roadmap": {"phases": [
            {"type": "intern", "name": "某司实习"},
            {"type": "learn", "name": "基础"},
        ]}
    }, ensure_ascii=False))["roadmap"]

    intern_ph, learn_ph = roadmap["phases"]
    assert intern_ph["jd_status"] == "pending_user_import"
    assert intern_ph["confirmed"] is False
    assert intern_ph["company"] == "" and intern_ph["jd"] is None
    assert learn_ph["jd_status"] == "not_required"


def test_save_roadmap_soft_check_and_html(temp_profile):
    """软校验：占位未确认/jd 无据提示；确认后消除；定稿自动产出路线图 HTML。"""
    from src.server import save_roadmap

    base = {
        "roadmap": {"strategy_summary": "测试", "phases": [
            {"type": "intern", "name": "某公司实习", "company": "某公司"},
            {"type": "project", "name": "做RAG项目", "jd": {"requirements": ["LangGraph"]}},
            {"type": "intern", "name": "已确认实习", "company": "乙公司", "jd_status": "pending_user_import", "confirmed": True},
        ]}
    }

    # 未确认占位 + jd 有内容无依据 → 均应提示；已确认的占位不提示
    result = json.loads(save_roadmap(json.dumps(base, ensure_ascii=False)))
    assert result["context"]["phase"] == "roadmap_saved"
    msg = result["message"]
    assert "某公司实习" in msg and "占位" in msg          # 未确认占位被提示
    assert "做RAG项目" in msg and "has_jd" in msg         # jd 有内容但未标注依据被提示
    assert "已确认实习" not in msg or "已确认" in msg      # confirmed 的占位不再提示（其名不含警告词）

    # 全部满足约束 → 无警告
    clean = {
        "roadmap": {"strategy_summary": "测试", "phases": [
            {"type": "intern", "name": "某公司实习", "company": "某公司",
             "jd_status": "pending_user_import", "confirmed": True},
            {"type": "project", "name": "做RAG项目", "jd": {"requirements": ["LangGraph"]},
             "jd_status": "has_jd"},
        ]}
    }
    result2 = json.loads(save_roadmap(json.dumps(clean, ensure_ascii=False)))
    assert "依据待确认" not in result2["message"]

    # 定稿自动产出路线图 HTML
    assert "career_kit_roadmap.html" in result2["message"]


def test_export_dashboard_roadmap_map(temp_profile):
    """活地图：mode=roadmap 含公司/占位徽标/执行进度/当前阶段高亮。"""
    from src.models import Task
    from src.server import export_dashboard

    p = profile_module.load_profile()
    p.plan = {"roadmap": {"strategy_summary": "先实习后冲刺", "phases": [
        {"id": "phase_1", "type": "intern", "name": "某公司实习", "company": "某公司",
         "rationale": "对双非友好", "jd_status": "pending_user_import"},
        {"id": "phase_2", "type": "learn", "name": "基础冲刺", "milestones": [
            {"name": "M1", "tasks": [{"name": "刷题"}, {"name": "项目"}]}
        ]},
    ]}}
    p.tasks = [
        Task(id="task_001", name="刷题", phase_id="phase_2"),
        Task(id="task_002", name="项目", phase_id="phase_2", status="completed"),
    ]
    p.gap = {"start_level": "中厂"}
    profile_module.save_profile(p)

    out = export_dashboard(mode="roadmap")
    assert "career_kit_roadmap.html" in out

    path = Path(out.split("：")[1].splitlines()[0].strip())
    html = path.read_text(encoding="utf-8")
    assert "职业地图" in html
    assert "某公司" in html and "对双非友好" in html      # 公司名 + 推荐理由
    assert "待导入真实 JD" in html                        # 占位徽标
    assert "起点层级" in html and "中厂" in html           # start_level 展示
    assert "career-data" in html                          # 数据 JSON 嵌入
    assert "[当前]" in html                                # 当前阶段高亮
    assert "免 JD" in html                                 # learn 阶段徽标
    assert "export-btn" in html and "reset-btn" in html    # 可交互打卡按钮
    assert "localStorage" in html                          # 本地持久化
    assert 'type="checkbox"' in html                       # 任务勾选打卡
    # 服务端进度数据：phase_2 完成 1/2 正确嵌入数据 JSON
    import json as _json
    m = _json.loads(html.split('id="career-data">')[1].split('</script>')[0])
    p2 = next(p for p in m["phases"] if p["id"] == "phase_2")
    assert p2["done"] == 1 and p2["total"] == 2


def test_explore_goals_returns_methodology(temp_profile):
    """explore_goals 返回目标选择方法论上下文，供 LLM 引导用户定方向。"""
    from src.server import explore_goals, intake

    # 档案还没建档 → 结构化错误
    result = json.loads(explore_goals())
    assert result.get("isError") is True
    assert result["code"] == "MISSING_DATA"

    # 建档后 → 返回方法论
    intake("who", '{"name": "小白", "status": "应届"}')
    intake("have", '{"skills": [], "experience_level": "零基础"}')

    out = json.loads(explore_goals())
    assert not out.get("isError")
    m = out["methodology"]
    assert m["name"] == "目标选择"
    assert m.get("principles"), "方法论应有 principles"
    assert any("三轴" in p for p in m["principles"])
    assert "fetch_company_jobs" in out["instructions"]
    assert "intake" in out["instructions"]


def test_explore_goals_records_journey(temp_profile):
    """explore_goals 记录启动到 journey，不污染 want。"""
    from src.server import explore_goals, intake

    intake("who", '{"name": "小白"}')
    intake("have", '{"skills": []}')

    explore_goals()
    profile = profile_module.load_profile()
    assert profile.journey and profile.journey[-1].phase == "analysis"
    assert profile.journey[-1].decision == "启动目标选择"
    assert not profile.want, "explore_goals 不应直接写入目标——目标由用户在对话中选定后经 intake 写入"


def test_explore_goals_methodology_yaml_exists():
    """goal_selection.yaml 方法论文件存在且含关键纪律。"""
    from src.tools.methodology import load_methodology

    data = load_methodology("goal_selection")
    assert data["name"] == "目标选择"
    m = data["methodology"]
    phases = {p["id"] for p in m["phases"]}
    assert {"probe_reality", "gather_market", "propose_directions", "decide"} <= phases
    text = str(m)
    assert "experience_level" in text  # 零基础如实记录
    assert "不编造" in text or "绝不" in text  # 数据纪律


def test_analyze_gaps_rejects_without_goal(temp_profile):
    """链路守卫：want 为空或仅模糊表述时 analyze_gaps 拒绝并引导 explore_goals。"""
    from src.server import analyze_gaps, intake

    intake("who", '{"name": "小白", "status": "应届"}')
    intake("have", '{"skills": [], "experience_level": "零基础"}')

    result = json.loads(analyze_gaps())
    assert result.get("isError") is True
    assert result["code"] == "MISSING_DATA"
    assert "explore_goals" in result["details"].get("suggestion", "")
    assert not profile_module.load_profile().gap, "不应产生差距分析"

    # 补上实质目标后放行
    intake("want", '{"target_role": "AI 应用开发"}')
    out = analyze_gaps()
    assert "差距分析" in out or "methodologies" in out


def test_analyze_gaps_rejects_fuzzy_want(temp_profile):
    """want 只有 raw（'想转行'）这种模糊表述 → 仍拒绝，引导 explore_goals。"""
    from src.server import analyze_gaps, intake

    intake("who", '{"name": "张三"}')
    intake("have", '{"skills": ["Python"]}')
    intake("want", "想转行")  # 非 JSON → raw

    result = json.loads(analyze_gaps())
    assert result.get("isError") is True
    assert "explore_goals" in result["details"].get("suggestion", "")


def test_workflow_status_routes_to_explore_goals_when_no_goal(temp_profile):
    """get_workflow_status：finalize 后无目标 → next_step 指向 explore_goals。"""
    from src.server import finalize_profile, get_workflow_status, intake

    intake("who", '{"name": "小白"}')
    intake("have", '{"skills": [], "experience_level": "零基础"}')
    finalize_profile()

    out = get_workflow_status()
    assert "explore_goals" in out

    # 有目标 → next_step 指向 analyze_gaps
    intake("want", '{"target_role": "AI 应用开发"}')
    out2 = get_workflow_status()
    assert "analyze_gaps" in out2


def test_finalize_profile_reminds_when_no_goal(temp_profile):
    """finalize_profile：无目标时返回目标缺失提醒。"""
    from src.server import finalize_profile, intake

    intake("who", '{"name": "小白"}')
    intake("have", '{"skills": [], "experience_level": "零基础"}')

    out = finalize_profile()
    assert "目标缺失" in out and "explore_goals" in out

    intake("want", '{"target_role": "前端工程师"}')
    out2 = finalize_profile()
    assert "目标缺失" not in out2


def test_explore_goals_guards_when_goal_exists(temp_profile):
    """explore_goals：已有实质目标时提示确认，不直接重新探索。"""
    from src.server import explore_goals, intake

    intake("who", '{"name": "张三"}')
    intake("have", '{"skills": ["Python"]}')
    intake("want", '{"target_role": "AI 应用开发"}')

    out = explore_goals()
    assert "已有目标" in out
    assert "analyze_gaps" in out
    assert "methodology" not in out  # 未直接返回方法论


def test_trigger_insight_event_available_without_tasks(temp_profile):
    """BUG 修复回归：event 型洞察在无任务时可用（漏斗软提示依赖它）。"""
    from src.server import record_application, trigger_insight

    record_application(company="字节", role="Agent 实习")
    record_application(
        company="字节", role="Agent 实习", status="interview", application_id="app_001"
    )

    out = _parse(
        trigger_insight(trigger_type="event", event_description="进入字节 Agent 实习面试")
    )
    assert "prompt" in out
    assert out["context"]["phase"] == "insight_ready"

    # 漏斗事实块应进入 prompt（归因点依赖）
    assert "漏斗" in out["prompt"] or "投递" in out["prompt"]


def test_trigger_insight_stage_audit_still_blocked_without_tasks(temp_profile):
    """stage_audit 在无任务时仍守卫（引导先建任务）。"""
    from src.server import trigger_insight

    out = _parse(trigger_insight(trigger_type="stage_audit"))
    assert out["context"]["phase"] == "no_tasks"


def test_record_application_schema_company_optional():
    """FastMCP 生成 schema 的运行时保证：company 可选（更新路径不再强制传），notes 在列。"""
    from src.server import mcp

    tools = {t.name: t for t in mcp._tool_manager.list_tools()}
    schema = tools["record_application"].parameters
    assert "company" not in (schema.get("required") or [])
    assert "notes" in schema["properties"]


def test_apply_insight_end_to_end(temp_profile):
    """BUG-005 回归：apply_insight 可导入、可执行、调整可落地。"""
    from src.models import Task
    from src.server import apply_insight, trigger_insight

    profile = profile_module.load_profile()
    profile.tasks = [Task(id="task_001", name="任务A", phase_id="phase_1")]
    profile_module.save_profile(profile)

    prepared = _parse(trigger_insight(trigger_type="stage_audit"))
    assert "prompt" in prepared

    insight = json.dumps({
        "trigger_type": "stage_audit",
        "status": "on_track",
        "summary": "任务正常推进",
        "insights": ["刷题节奏稳定"],
        "adjustment_needed": True,
        "adjustment_type": "auto",
        "adjustment_reason": "掌握速度快，加深难度",
        "changes": [
            {"type": "add_task", "details": {"name": "任务A（深入）"}},
            {"type": "modify_task", "task_id": "task_001", "details": {"priority": "high"}},
        ],
        "user_message": "继续保持",
    }, ensure_ascii=False)

    applied = _parse(apply_insight(insight_json=insight))
    assert applied["context"]["phase"] == "adjustment_applied"

    final = profile_module.load_profile()
    assert any(t.name == "任务A（深入）" for t in final.tasks)
    assert final.get_task("task_001").priority == "high"
    assert final.adjustments[-1].trigger_type == "stage_audit"


# ============ 路线图质量硬校验（BUG-003 回归） ============


def test_save_roadmap_hard_check_required_fields(temp_profile):
    """硬校验：learn 外阶段缺 resume_value、KPI 缺量化指标 → 提示。"""
    from src.server import intake, save_roadmap

    intake("who", '{"name": "张三", "graduation_year": "2028"}')
    intake("have", '{"skills": ["Python"], "experience_level": "小厂"}')
    intake("want", '{"target_role": "AI 工程师"}')

    roadmap = {
        "roadmap": {
            "strategy_summary": "测试",
            "start_level": "小厂",
            "phases": [
                {"type": "intern", "name": "某公司实习", "company": "某公司", "target_level": "小厂"},
                {"type": "project", "name": "做项目", "kpi": {"metric": "完成1个项目", "target": "1个"}},
            ],
        }
    }
    result = json.loads(save_roadmap(json.dumps(roadmap, ensure_ascii=False)))
    msg = result["message"]
    assert "硬校验" in msg
    assert "resume_value" in msg
    assert result["context"]["hard_issues"], "应收集到必填缺失问题"


def test_save_roadmap_hard_check_level_jump(temp_profile):
    """硬校验：起点小厂但 intern 目标大厂 → 超连续范围提示。"""
    from src.server import intake, save_roadmap

    intake("who", '{"name": "张三"}')
    intake("have", '{"skills": ["Python"], "experience_level": "小厂"}')
    intake("want", '{"target_role": "AI 工程师"}')

    roadmap = {
        "roadmap": {
            "strategy_summary": "测试",
            "start_level": "小厂",
            "phases": [
                {"type": "intern", "name": "大厂实习", "company": "某大厂",
                 "target_level": "大厂", "resume_value": "大厂实习经历",
                 "kpi": {"metric": "入职", "target": "1个"}},
            ],
        }
    }
    result = json.loads(save_roadmap(json.dumps(roadmap, ensure_ascii=False)))
    assert "超出起点" in result["message"] or "高于起点" in result["message"]


def test_save_roadmap_hard_check_graduation(temp_profile):
    """硬校验：阶段面向届早于用户毕业届 → 届别不匹配提示。"""
    from src.server import intake, save_roadmap

    intake("who", '{"name": "张三", "graduation_year": "2028"}')
    intake("have", '{"skills": ["Python"]}')
    intake("want", '{"target_role": "AI 工程师"}')

    roadmap = {
        "roadmap": {
            "strategy_summary": "测试",
            "phases": [
                {"type": "intern", "name": "2027届实习", "company": "某公司",
                 "graduation_year": "2027", "resume_value": "实习经历",
                 "kpi": {"metric": "入职", "target": "1个"}},
            ],
        }
    }
    result = json.loads(save_roadmap(json.dumps(roadmap, ensure_ascii=False)))
    assert "面向届 2027" in result["message"] and "2028" in result["message"]


def test_save_roadmap_no_start_level_passes(temp_profile):
    """无 start_level/届别数据时放行（有数据才挡，兼容旧数据）。"""
    from src.server import intake, save_roadmap

    intake("who", '{"name": "张三"}')
    intake("have", '{"skills": ["Python"]}')
    intake("want", '{"target_role": "AI 工程师"}')

    roadmap = {
        "roadmap": {
            "strategy_summary": "测试",
            "phases": [
                {"type": "project", "name": "做项目", "resume_value": "项目经历",
                 "kpi": {"metric": "完成", "target": "1个"}},
            ],
        }
    }
    result = json.loads(save_roadmap(json.dumps(roadmap, ensure_ascii=False)))
    assert result["context"]["phase"] == "roadmap_saved"
    assert not result["context"]["hard_issues"]


def test_intake_who_guides_graduation_year(temp_profile):
    """intake(who)：无毕业届时返回引导；已填则不重复提示。"""
    from src.server import intake

    out = intake("who", '{"name": "张三"}')
    assert "graduation_year" in out

    out2 = intake("who", '{"graduation_year": "2028"}')
    assert "graduation_year" not in out2


def test_roadmap_yaml_has_rubric_and_audit():
    """SOP 规则化：roadmap.yaml 含 start_level 打分表与审计清单；resume_screening 含负面信号。"""
    from pathlib import Path

    import yaml

    sop_dir = Path(__file__).parent.parent / "sop"
    roadmap = yaml.safe_load((sop_dir / "roadmap.yaml").read_text(encoding="utf-8"))
    m = roadmap["methodology"]
    assert "start_level_rubric" in m, "roadmap.yaml 缺 start_level 打分表"
    assert "dimensions" in m["start_level_rubric"], "打分表缺维度"
    assert "mapping" in m["start_level_rubric"], "打分表缺档位映射"
    assert "audit_checklist" in m, "roadmap.yaml 缺审计清单"
    assert len(m["audit_checklist"]["items"]) >= 5, "审计清单项数不足"

    resume = yaml.safe_load((sop_dir / "resume_screening.yaml").read_text(encoding="utf-8"))
    assert "resume_red_flags" in resume["methodology"]["output_schema"], "缺负面信号审计输出字段"


def test_generate_roadmap_returns_step_template(temp_profile):
    """generate_roadmap 返回 step_template（6 步工作流）。"""
    from src.server import generate_roadmap, intake, save_gap_analysis

    intake("who", '{"name": "张三"}')
    intake("have", '{"skills": ["Python"]}')
    intake("want", '{"target_role": "AI 工程师"}')
    save_gap_analysis(json.dumps({
        "match_score": 50, "match_level": "partial_match",
        "skill_gaps": [{"skill": "AI", "priority": "high", "current_level": "无",
                        "required_level": "入门", "how_to_improve": "学习", "source": "测试"}],
    }, ensure_ascii=False))

    out = _parse(generate_roadmap())
    assert "step_template" in out
    assert len(out["step_template"]) == 6
    assert out["step_template"][0]["name"] == "起点判定"
    assert out["step_template"][0]["checkpoint"] is True
    assert any(s["name"] == "审计" for s in out["step_template"])


# ============ BUG-001：简历验证防线 ============


def test_parse_resume_requires_verification(tmp_path, temp_profile):
    """BUG-001 回归：parse_resume 把简历定位为候选素材，要求逐项求证而非直接灌库。"""
    from src.server import parse_resume

    resume = tmp_path / "resume.md"
    resume.write_text("精通 Python，做过爬虫项目", encoding="utf-8")

    out = parse_resume(str(resume))
    assert "候选素材" in out, "简历应定位为候选素材"
    assert "简历有美化成分" in out
    assert "逐项向用户求证" in out or "求证" in out
    assert "user_verified" in out or "verified" in out
    assert "authorship" in out and "control_level" in out, \
        "BUG-021：应引导 per-skill 作者身份与把控度自评"
    assert "self_assessment" in out, "BUG-021：应引导整份简历自评"
    assert "不得照抄简历" in out


# ============ BUG-004：详细路线与打卡点 ============


def test_detail_current_phase_requires_tasks(temp_profile):
    """detail_current_phase：无任务时拒绝。"""
    from src.server import detail_current_phase

    data = json.loads(detail_current_phase())
    assert data.get("isError") is True
    assert data["code"] == "MISSING_DATA"


def test_detail_current_phase_and_save(temp_profile):
    """BUG-004：detail_current_phase 返回方法论+当前阶段；save_current_detail 保存并引导重新 generate_tasks。"""
    from src.models import Task
    from src.server import detail_current_phase, save_current_detail

    p = profile_module.load_profile()
    p.plan = {"roadmap": {"phases": [
        {"id": "phase_1", "name": "基础学习", "milestones": [
            {"name": "M1", "tasks": [{"name": "学Python"}, {"name": "学LangGraph"}]}
        ]},
        {"id": "phase_2", "name": "项目实战"},
    ]}}
    p.tasks = [
        Task(id="task_001", name="学Python", phase_id="phase_1"),
        Task(id="task_002", name="学LangGraph", phase_id="phase_1"),
        Task(id="task_003", name="推进阶段：项目实战", phase_id="phase_2"),
    ]
    profile_module.save_profile(p)

    out = _parse(detail_current_phase())
    assert "detailed_route" in out["methodology"]["name"] or out["methodology"].get("name") == "当前阶段详细路线"
    assert out["current_phase"]["phase_id"] == "phase_1", "应定位第一个有未完成任务的阶段"

    detail = {
        "phase_id": "phase_1",
        "tasks": [
            {"name": "学Python", "checkin_mode": "daily", "checkin_goal": 30, "priority": "high"},
            {"name": "学LangGraph", "checkin_mode": "percent", "checkin_goal": 80, "priority": "medium"},
        ],
    }
    saved = _parse(save_current_detail(json.dumps(detail, ensure_ascii=False)))
    assert saved["context"]["phase"] == "detail_saved"
    assert "generate_tasks" in saved["next_steps"]


def test_generate_tasks_merges_checkin_points(temp_profile):
    """BUG-004：generate_tasks 从 current_detail 合并打卡点字段到任务。"""
    from src.models import Task
    from src.server import generate_tasks

    p = profile_module.load_profile()
    p.plan = {"current_detail": {"phase_id": "phase_1", "tasks": [
        {"name": "学Python", "checkin_mode": "daily", "checkin_goal": 30},
    ]}, "roadmap": {"phases": [
        {"id": "phase_1", "name": "基础学习", "milestones": [
            {"name": "M1", "tasks": [{"name": "学Python"}]}
        ]},
    ]}}
    p.tasks = [Task(id="task_001", name="学Python", phase_id="phase_1")]
    profile_module.save_profile(p)

    _parse(generate_tasks())
    final = profile_module.load_profile()
    t = final.get_task("task_001")
    assert t.checkin_mode == "daily", "打卡点未合并"
    assert t.checkin_goal == 30


def test_checkin_daily_and_percent(temp_profile):
    """BUG-004：checkin_task 支持 daily 按天累加 / percent 按比例累加，达目标才完成。"""
    from src.models import Task
    from src.server import checkin_task

    p = profile_module.load_profile()
    p.plan = {"roadmap": {"phases": []}}
    p.tasks = [
        Task(id="task_d", name="刷题30天", phase_id="phase_1", checkin_mode="daily", checkin_goal=3),
        Task(id="task_p", name="学文档到80%", phase_id="phase_1", checkin_mode="percent", checkin_goal=80),
    ]
    profile_module.save_profile(p)

    # daily：3 天才完成
    out1 = checkin_task(task_id="task_d", status="completed", amount=1)
    assert "累计 1/3 天" in out1
    out2 = checkin_task(task_id="task_d", status="completed", amount=1)
    assert "累计 2/3 天" in out2
    out3 = checkin_task(task_id="task_d", status="completed", amount=1)
    assert "已打卡" in out3
    assert profile_module.load_profile().get_task("task_d").status == "completed"

    # percent：累计到 80% 才完成
    out4 = checkin_task(task_id="task_p", status="completed", amount=40)
    assert "40%" in out4 and "目标 80%" in out4
    out5 = checkin_task(task_id="task_p", status="completed", amount=40)
    assert "已打卡" in out5
    assert profile_module.load_profile().get_task("task_p").status == "completed"


def test_save_roadmap_guides_execution_start(temp_profile):
    """BUG-004：save_roadmap 文案引导开始第一阶段执行。"""
    from src.server import intake, save_roadmap

    intake("who", '{"name": "张三"}')
    intake("have", '{"skills": ["Python"]}')
    intake("want", '{"target_role": "AI 工程师"}')

    roadmap = {"roadmap": {"strategy_summary": "测试", "phases": [
        {"type": "project", "name": "做项目", "resume_value": "项目",
         "kpi": {"metric": "完成", "target": "1个"}},
    ]}}
    out = _parse(save_roadmap(json.dumps(roadmap, ensure_ascii=False)))
    assert "开始第一阶段" in out["message"] or "引导用户" in out["message"]


# ============ 差距分析内容质量门（BUG-002/003 收尾：不编造落成代码） ============

def test_gap_gate_rejects_missing_source(temp_profile):
    """skill_gaps 缺 source（无真实数据来源）→ 拒绝落盘。"""
    from src.server import save_gap_analysis

    bad = json.dumps({
        "match_score": 60,
        "skill_gaps": [{"skill": "RAG", "priority": "high"}],
    }, ensure_ascii=False)
    result = json.loads(save_gap_analysis(gap_json=bad))
    assert result.get("isError") is True
    assert result["code"] == "INCOMPLETE_ANALYSIS"
    assert any("source" in i for i in result["details"]["issues"])
    assert not profile_module.load_profile().gap


def test_gap_gate_rejects_empty_gaps(temp_profile):
    """空 skill_gaps → 拒绝（差距分析必须至少产出一条差距）。"""
    from src.server import save_gap_analysis

    bad = json.dumps({"match_score": 60, "skill_gaps": []}, ensure_ascii=False)
    result = json.loads(save_gap_analysis(gap_json=bad))
    assert result.get("isError") is True
    assert result["code"] == "INCOMPLETE_ANALYSIS"


def test_gap_gate_rejects_out_of_range_score(temp_profile):
    """match_score 越界 → 拒绝。"""
    from src.server import save_gap_analysis

    bad = json.dumps({
        "match_score": 180,
        "skill_gaps": [{"skill": "RAG", "source": "JD"}],
    }, ensure_ascii=False)
    result = json.loads(save_gap_analysis(gap_json=bad))
    assert result.get("isError") is True
    assert result["code"] == "INCOMPLETE_ANALYSIS"


def test_gap_gate_rejects_incomplete_red_flags(temp_profile):
    """resume_red_flags 缺 risk/evidence_fix → 拒绝（负面信号必须给对策）。"""
    from src.server import save_gap_analysis

    bad = json.dumps({
        "match_score": 60,
        "skill_gaps": [{"skill": "RAG", "source": "JD"}],
        "resume_red_flags": [{"signal": "独立开发"}],
    }, ensure_ascii=False)
    result = json.loads(save_gap_analysis(gap_json=bad))
    assert result.get("isError") is True
    assert result["code"] == "INCOMPLETE_ANALYSIS"
    assert any("resume_red_flags" in i for i in result["details"]["issues"])


def test_gap_gate_accepts_anchored_analysis(temp_profile):
    """锚定真实数据来源的完整差距分析 → 正常保存。"""
    from src.server import save_gap_analysis

    good = json.dumps({
        "match_score": 58,
        "skill_gaps": [{"skill": "协作", "priority": "high", "source": "字节 JD"}],
        "resume_red_flags": [{"signal": "独立开发", "risk": "缺协作证据",
                              "narrative_fix": "强调契约设计", "evidence_fix": "开源 PR"}],
    }, ensure_ascii=False)
    result = _parse(save_gap_analysis(gap_json=good))
    assert result["context"]["phase"] == "gap_saved"
    assert profile_module.load_profile().gap["match_score"] == 58


# ============ 首启零抓取降级路径：抓取失败要引导手动导入 ============

def test_fetch_failure_suggests_manual_import(temp_profile, monkeypatch):
    """抓取失败时恢复建议包含手动导入（import_jd），流程不停摆。"""
    import asyncio

    import src.server as server_module
    import src.tools.data_tools as data_tools

    monkeypatch.setattr(
        data_tools, "search_company_jobs",
        lambda *a, **k: {"error": "需要登录 BOSS 直聘", "available": []},
    )
    result = json.loads(asyncio.run(server_module.fetch_company_jobs(company="boss")))
    assert result.get("isError") is True
    assert "import_jd" in result["details"]["recovery"]


# ============ 三档目标推荐（BUG-006） ============

def test_explore_goals_includes_three_tier_targets(temp_profile):
    """BUG-006：explore_goals 指引包含三档目标（冲/稳/保）。"""
    from src.server import explore_goals, intake

    intake("who", '{"name": "张三", "status": "应届生"}')
    intake("have", '{"experience_level": "零基础"}')

    out = json.loads(explore_goals())
    ins = out["instructions"]
    assert "三档" in ins
    assert "挑战" in ins and "兜底" in ins


def test_goal_selection_has_three_tier_phase():
    """BUG-006：目标选择方法论含三档目标阶段与输出 schema。"""
    from src.tools.methodology import load_methodology

    m = load_methodology("goal_selection")["methodology"]
    phase_ids = [p.get("id") for p in m.get("phases", [])]
    assert "propose_target_tiers" in phase_ids
    assert "target_tiers" in m.get("output_schema", {})



