# 转行场景

> 前端工程师转行 AI Agent 工程师

## 用户背景

- 当前：前端工程师，1年经验
- 目标：AI Agent 工程师
- 期望薪资：20k-30k
- 目标城市：上海

## 工作流

### 1. 建档

```
start_session()
intake(section="who", data='{"name":"张三", "education":"计算机本科", "status":"在职"}')
intake(section="have", data='{
  "core_skills": [
    {"skill":"JavaScript","level":"熟练","evidence":"1年前端项目","user_verified":true},
    {"skill":"React","level":"熟练","evidence":"独立完成2个项目","user_verified":true}
  ],
  "experience":"1年前端开发"
}')
intake(section="want", data='{"target_role":"AI Agent 工程师", "salary":"20k-30k", "city":"上海"}')
finalize_profile()
```

### 2. 分析（先抓真实数据，再分析）

```
list_data_sources()
get_scraper_guide(company="boss")
fetch_company_jobs(company="boss", params='{"keyword":"AI Agent", "city":"上海"}')
fetch_jd_detail(url="...")
analyze_gaps()
save_gap_analysis(gap_json='{
  "match_score": 45,
  "match_level": "partial_match",
  "strengths": [
    {"area": "前端开发", "description": "1 年前端经验，能独立交付页面与组件",
     "resume_highlight": "独立负责 2 个 React 项目", "interview_talk": "强调工程化与交付能力"}
  ],
  "resume_optimization": {
    "ats_keywords": ["JavaScript", "React", "Node.js"],
    "missing_keywords": ["Python", "LLM", "LangChain", "RAG"],
    "highlight_projects": [
      {"project": "React 后台系统", "how_to_package": "突出组件设计与性能优化",
       "quantified_result": "首屏加载降低 30%"}
    ],
    "resume_tips": ["把前端项目改写成「问题-方案-结果」结构"],
    "missing_experiences": [
      {"experience": "LLM 应用开发", "how_to_create": "完成一个 RAG 项目并开源"}
    ]
  },
  "interview_preparation": {
    "must_prepare": [
      {"topic": "Python 基础", "type": "八股", "priority": "high",
       "estimated_time": "2 周", "prepare_advice": "语法 + 常用库 + 手写题"}
    ],
    "project_deep_dive": [
      {"project": "React 后台系统", "likely_questions": ["性能优化怎么做的？"],
       "key_points": ["定位瓶颈", "量化收益"], "star_story": "S:页面慢 T:优化 A:分包+缓存 R:快 30%"}
    ],
    "system_design_topics": [{"topic": "RAG 检索链路", "framework": "数据摄入→切分→检索→生成→评估"}],
    "behavioral_questions": [{"question": "为什么转 AI？", "story_template": "兴趣 + 已有工程能力 + 已付出行动"}],
    "study_plan": {"week_1": ["Python 基础"], "week_2": ["LangChain + RAG 入门"]}
  },
  "skill_gaps": [
    {"skill": "Python", "priority": "high", "current_level": "基础",
     "required_level": "熟练", "how_to_improve": "系统学习并完成 2 个小项目", "source": "BOSS直聘 JD"},
    {"skill": "LLM", "priority": "high", "current_level": "无",
     "required_level": "了解原理", "how_to_improve": "学习 Transformer 与提示工程", "source": "BOSS直聘 JD"},
    {"skill": "LangChain", "priority": "medium", "current_level": "无",
     "required_level": "能独立开发", "how_to_improve": "完成官方教程并复刻示例", "source": "BOSS直聘 JD"},
    {"skill": "RAG", "priority": "medium", "current_level": "无",
     "required_level": "能独立搭建", "how_to_improve": "做一个带评测的 RAG 项目", "source": "BOSS直聘 JD"}
  ],
  "priority_actions": [
    {"action": "学习 Python 基础", "timeline": "2 周", "impact": "高", "difficulty": "中"},
    {"action": "完成一个 RAG 项目", "timeline": "4 周", "impact": "高", "difficulty": "高"}
  ],
  "market_context": "上海 AI Agent 岗位普遍要求 Python + LLM + RAG 实战经验"
}')
```

### 3. 规划（只定顺序与标准，不定时间）

```
generate_roadmap()
save_roadmap(roadmap_json='{
  "strategy_summary": "先补 Python/LLM 基础，再做 RAG 项目，最后冲 AI Agent 岗位",
  "phases": [
    {
      "type": "learn",
      "name": "基础补齐",
      "goal": "掌握 Python、LLM 与 LangChain 基础",
      "kpi": {"metric": "完成专题", "target": "3 个", "evidence": "笔记与练习"},
      "resume_value": "",
      "milestones": [
        {"name": "Python 基础", "done_criteria": "能独立写出数据处理脚本",
         "tasks": [{"name": "学习 Python 语法与常用库", "priority": "high"}]},
        {"name": "LLM 与 LangChain", "done_criteria": "能跑通一个 LangChain Demo",
         "tasks": [{"name": "完成 LangChain 官方教程", "priority": "high"}]}
      ]
    },
    {
      "type": "project",
      "name": "RAG 项目实战",
      "goal": "做出可展示的 RAG 应用",
      "kpi": {"metric": "项目数", "target": "1 个", "evidence": "GitHub 仓库"},
      "resume_value": "独立开发 RAG 应用并量化检索效果",
      "milestones": [
        {"name": "RAG Demo", "done_criteria": "端到端可运行并附评测",
         "tasks": [{"name": "实现检索与生成链路", "priority": "high"}]}
      ]
    }
  ]
}')
```

> 不要写 `duration` 等时长字段；用户想要日程时，在对话中直接把任务写成
> markdown/HTML 文档交付，时间由用户自己填。

### 4. 任务执行

```
generate_tasks()
get_next_tasks()   # 从返回值中取 task_id
checkin_task(task_id="<get_next_tasks 返回的 ID>", status="completed", notes="Python 基础学完")
```

### 5. 洞察调整（阶段完成后审计）

```
trigger_insight(trigger_type="stage_audit")
apply_insight(insight_json='{
  "trigger_type": "stage_audit",
  "status": "on_track",
  "summary": "基础阶段完成",
  "insights": ["学习速度正常"],
  "adjustment_needed": false,
  "adjustment_type": "auto",
  "adjustment_reason": "",
  "changes": [],
  "user_message": "继续保持"
}')
```
