"""E2E 合成用户数据——真实格式，用于确定性核心套件。"""

from __future__ import annotations

from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"

WHO = {
    "name": "林舟",
    "status": "应届生",
    "education": "本科 计算机科学",
    "graduation_year": "2027",
    "city": "深圳",
}

HAVE = {
    "skills": [
        {
            "skill": "Python",
            "level": "能独立写后端服务",
            "evidence": "课程项目：FastAPI 待办服务，含鉴权与 PostgreSQL",
            "user_verified": True,
            "authorship": "self_written",
            "control_level": 7,
        },
        {
            "skill": "React",
            "level": "能改业务页面",
            "evidence": "实习期间维护 3 个后台页面",
            "user_verified": True,
            "authorship": "ai_assisted",
            "control_level": 5,
        },
    ],
    "self_assessment": {
        "resume_trust": "medium",
        "notes": "Python 项目全部手写；React 页面为 AI 生成+实习期验证迭代",
    },
    "experience_level": "小厂",
    "projects": ["FastAPI 待办服务", "React 运营后台"],
}

WANT = {
    "target_role": "AI Agent 开发工程师",
    "city": "深圳",
    "salary": "20k-30k",
    "target_companies": ["腾讯", "字节跳动"],
    "experience_level": "小厂",
}

AGENT_JD = """# AI Agent 开发工程师（校招）

## 岗位职责
1. 参与 Agent 编排、工具调用与 RAG 链路的开发与评测；
2. 负责 Prompt 设计、上下文管理与效果回归；
3. 与产品、算法协作，把 Demo 推进到可上线服务。

## 任职要求
1. 熟悉 Python，掌握 FastAPI 或同类 Web 框架；
2. 理解 LLM 基本原理，有 LangChain / LangGraph 实践经验；
3. 有向量数据库、检索增强生成（RAG）项目经验优先；
4. 能独立定位问题并给出可验证的改进方案。
"""

GAP = {
    "match_score": 58,
    "match_level": "partial_match",
    "strengths": [
        {
            "area": "Python 后端",
            "description": "有 FastAPI 项目与鉴权经验",
            "resume_highlight": "把鉴权与数据库设计写成量化指标",
        }
    ],
    "resume_optimization": {
        "ats_keywords": ["Python", "FastAPI", "RAG", "Agent", "LLM"],
        "missing_keywords": ["LangGraph", "向量数据库", "评测"],
        "highlight_projects": [
            {"project": "FastAPI 待办服务", "how_to_package": "强调接口设计与鉴权", "quantified_result": "支持 1000 用户"}
        ],
    },
    "interview_preparation": {
        "must_prepare": [
            {"topic": "RAG 链路", "type": "项目", "priority": "high", "prepare_advice": "准备召回失败的排查案例"}
        ],
        "project_deep_dive": [
            {"project": "FastAPI 待办服务", "likely_questions": ["如何做鉴权"], "key_points": ["JWT + 权限校验"]}
        ],
    },
    "skill_gaps": [
        {
            "skill": "LangGraph",
            "priority": "high",
            "current_level": "不了解",
            "required_level": "能独立编排 Agent",
            "is_hidden": False,
            "how_to_improve": "完成一个带工具调用与状态管理的 Agent",
            "source": "导入 JD：AI Agent 开发工程师",
        },
        {
            "skill": "RAG 评测",
            "priority": "high",
            "current_level": "无",
            "required_level": "能设计召回与答案质量评测",
            "is_hidden": True,
            "how_to_improve": "为 RAG demo 加离线评测集与指标",
            "source": "导入 JD：AI Agent 开发工程师",
        },
        {
            "skill": "向量数据库",
            "priority": "medium",
            "current_level": "了解概念",
            "required_level": "能选型与调参",
            "is_hidden": False,
            "how_to_improve": "用 pgvector 或 Chroma 做一个检索服务",
            "source": "导入 JD：AI Agent 开发工程师",
        },
    ],
    "resume_red_flags": [
        {
            "signal": "项目描述只有功能没有结果",
            "risk": "无法证明工程能力",
            "narrative_fix": "用问题-方案-结果结构重写",
            "evidence_fix": "补 QPS、延迟、用户数等指标",
        },
        {
            "signal": "React 页面主要由 AI 生成，人工只做验证迭代",
            "risk": "面试被要求手写组件/逐行讲解时暴露",
            "narrative_fix": "按把控度如实描述（能改业务页面，不写精通）",
            "evidence_fix": "补手写组件练习与 PR 记录",
        },
    ],
    "priority_actions": [
        {"action": "完成一个带工具调用的 Agent 项目", "impact": "high", "difficulty": "medium"},
        {"action": "为 RAG 项目补评测集与指标", "impact": "high", "difficulty": "medium"},
    ],
    "market_context": "深圳 AI Agent 校招岗位要求普遍包含 Python、RAG、Agent 编排与评测经验。",
    "start_level": "小厂",
}

ROADMAP = {
    "strategy_summary": "先补齐 Agent 工程能力，再用项目证明，最后冲目标公司实习。",
    "start_level": "小厂",
    "phases": [
        {
            "type": "learn",
            "name": "Agent 工程基础",
            "goal": "掌握工具调用、状态管理与 RAG 基础",
            "kpi": {"metric": "完成可运行 demo", "target": "1 个", "evidence": "GitHub 仓库"},
            "resume_value": "Agent 工程基础",
            "milestones": [
                {
                    "name": "LangGraph 基础",
                    "done_criteria": "能独立实现带状态与工具调用的 Agent",
                    "deliverable": "Agent demo 仓库",
                    "tasks": [
                        {"name": "学习 LangGraph 状态与节点", "description": "跑通官方 quickstart", "priority": "high"},
                        {"name": "实现工具调用 Agent", "description": "至少接入 2 个工具", "priority": "high"},
                    ],
                }
            ],
        },
        {
            "type": "project",
            "name": "RAG 评测项目",
            "goal": "做出可量化、可复现的 RAG 项目",
            "kpi": {"metric": "评测集", "target": "50 条问答", "evidence": "评测报告"},
            "resume_value": "RAG 检索与评测经验",
            "milestones": [
                {
                    "name": "检索链路",
                    "done_criteria": "支持文档入库、召回与重排",
                    "deliverable": "RAG 服务",
                    "tasks": [
                        {"name": "搭建向量检索服务", "description": "pgvector 或 Chroma", "priority": "high"},
                        {"name": "设计 RAG 评测集", "description": "覆盖召回与答案质量", "priority": "high"},
                    ],
                }
            ],
        },
        {
            "type": "intern",
            "name": "目标公司 Agent 实习",
            "company": "腾讯",
            "rationale": "Agent 布局重，校招有明确 Agent 岗位",
            "target_level": "小厂",
            "graduation_year": "2027",
            "jd": None,
            "jd_status": "pending_user_import",
            "confirmed": True,
            "resume_value": "大厂 Agent 实习经历",
            "kpi": {"metric": "拿到面试", "target": "1 次", "evidence": "面试邀约"},
            "milestones": [
                {
                    "name": "投递与面试",
                    "done_criteria": "完成简历投递并获得至少一次面试",
                    "tasks": [
                        {"name": "按 JD 重写简历", "description": "突出 Agent 与 RAG 项目", "priority": "high"},
                        {"name": "准备 RAG 项目追问", "description": "整理 10 个可能追问", "priority": "high"},
                    ],
                }
            ],
        },
    ],
}

DETAIL = {
    "phase_id": "phase_1",
    "tasks": [
        {"name": "学习 LangGraph 状态与节点", "checkin_mode": "daily", "checkin_goal": 7, "priority": "high"},
        {"name": "实现工具调用 Agent", "checkin_mode": "once", "priority": "high"},
        {"name": "搭建向量检索服务", "checkin_mode": "percent", "checkin_goal": 80, "priority": "high"},
    ],
}

INSIGHT = {
    "trigger_type": "stage_audit",
    "status": "on_track",
    "summary": "基础阶段完成，项目能力开始形成",
    "insights": ["Agent demo 已完成", "需要补评测证据"],
    "adjustment_needed": True,
    "adjustment_type": "auto",
    "adjustment_reason": "评测是目标岗位的隐性要求，提前补上",
    "changes": [
        {
            "type": "add_task",
            "details": {
                "name": "补充 RAG 评测报告",
                "description": "把评测集、指标与结论写进项目 README",
                "phase_id": "phase_2",
                "priority": "high",
            },
        }
    ],
    "user_message": "已为下一阶段补上评测任务。",
}


def resume_markdown() -> str:
    return """# 林舟

应届生 · 深圳 · Python / React

## 项目
- FastAPI 待办服务：JWT 鉴权、PostgreSQL、Docker 部署
- React 运营后台：3 个页面维护

## 技能
Python、FastAPI、React、SQL
"""


def resume_text() -> str:
    return "林舟\n应届生\nPython / React\nFastAPI 待办服务\nReact 运营后台\n"
