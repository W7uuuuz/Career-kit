# 技能提升场景

> 在职人员提升技能

## 用户背景

- 当前：AI Agent 工程师，1年经验
- 目标：提升技能，争取晋升或跳槽

## 工作流

### 1. 建档

```
start_session()
intake(section="who", data='{"name":"李四", "education":"计算机硕士", "status":"在职"}')
intake(section="have", data='{
  "core_skills": [
    {"skill":"Python","level":"熟练","evidence":"1年AI Agent开发","user_verified":true},
    {"skill":"LangChain","level":"熟练","evidence":"线上项目使用","user_verified":true},
    {"skill":"RAG","level":"熟练","evidence":"独立搭建检索链路","user_verified":true}
  ],
  "experience":"1年AI Agent开发"
}')
intake(section="want", data='{"target_role":"高级 AI Agent 工程师", "salary":"35k-50k", "city":"北京"}')
finalize_profile()
```

### 2. 分析（先抓真实数据，再分析）

```
list_data_sources()
get_scraper_guide(company="bytedance")
fetch_company_jobs(company="bytedance", params='{"keyword":"高级 AI Agent"}')
fetch_jd_detail(url="...")
analyze_gaps()
save_gap_analysis(gap_json='{
  "match_score": 70,
  "match_level": "partial_match",
  "strengths": [
    {"area": "Agent 开发", "description": "1 年 LangChain/RAG 实战",
     "resume_highlight": "独立负责线上 Agent 链路", "interview_talk": "强调端到端交付"}
  ],
  "resume_optimization": {
    "ats_keywords": ["Python", "LangChain", "RAG"],
    "missing_keywords": ["多Agent", "Agent评估", "性能优化"],
    "highlight_projects": [
      {"project": "线上 Agent", "how_to_package": "突出架构与稳定性",
       "quantified_result": "可用性 99.9%"}
    ],
    "resume_tips": ["补充多 Agent 协作与评估指标"],
    "missing_experiences": [
      {"experience": "多 Agent 系统", "how_to_create": "做一个双 Agent 协作项目"}
    ]
  },
  "interview_preparation": {
    "must_prepare": [
      {"topic": "多 Agent 架构", "type": "项目", "priority": "high",
       "estimated_time": "2 周", "prepare_advice": "讲清分工、通信与失败恢复"}
    ],
    "project_deep_dive": [
      {"project": "线上 Agent", "likely_questions": ["怎么做评估？"],
       "key_points": ["离线评测", "线上监控"], "star_story": "S:效果不稳 T:建评估 A:指标+回归 R:稳定提升"}
    ],
    "system_design_topics": [{"topic": "多 Agent 协作", "framework": "角色分工→通信→仲裁→观测"}],
    "behavioral_questions": [{"question": "为什么想晋升？", "story_template": "能力已超出当前职级 + 有落地证据"}],
    "study_plan": {"week_1": ["多 Agent 论文"], "week_2": ["评估流水线"]}
  },
  "skill_gaps": [
    {"skill": "多Agent系统", "priority": "high", "current_level": "了解",
     "required_level": "熟练", "how_to_improve": "设计并实现双 Agent 协作项目", "source": "字节跳动 JD"},
    {"skill": "Agent评估", "priority": "medium", "current_level": "了解",
     "required_level": "熟练", "how_to_improve": "搭建自动化评估流水线", "source": "字节跳动 JD"},
    {"skill": "性能优化", "priority": "medium", "current_level": "了解",
     "required_level": "熟练", "how_to_improve": "对现有项目做优化并量化", "source": "字节跳动 JD"}
  ],
  "priority_actions": [
    {"action": "学习多Agent系统设计", "timeline": "2 周", "impact": "高", "difficulty": "中"},
    {"action": "搭建 Agent 评估流水线", "timeline": "2 周", "impact": "高", "difficulty": "高"}
  ],
  "market_context": "字节跳动高级 AI Agent 岗位要求多 Agent 协作与评估经验"
}')
```

### 3. 规划（只定顺序与标准，不定时间）

```
generate_roadmap()
save_roadmap(roadmap_json='{
  "strategy_summary": "围绕多Agent系统深入，用项目落地，最后冲刺求职",
  "phases": [
    {
      "type": "learn",
      "name": "深入学习",
      "goal": "补齐多Agent系统、Agent评估与性能优化",
      "kpi": {"metric": "完成学习并产出笔记", "target": "3 个专题", "evidence": "技术笔记"},
      "resume_value": "",
      "milestones": [
        {"name": "多Agent系统", "done_criteria": "能设计双Agent协作架构",
         "tasks": [{"name": "阅读多Agent综述并做笔记", "priority": "high"}]},
        {"name": "Agent评估", "done_criteria": "能搭建自动化评估流水线",
         "tasks": [{"name": "实现离线评测脚本", "priority": "high"}]},
        {"name": "性能优化", "done_criteria": "现有项目关键指标提升有数据",
         "tasks": [{"name": "定位现有项目性能瓶颈", "priority": "medium"}]}
      ]
    },
    {
      "type": "project",
      "name": "项目实战",
      "goal": "用项目巩固所学",
      "kpi": {"metric": "GitHub star", "target": "30+", "evidence": "仓库链接"},
      "resume_value": "独立开发多Agent协作系统与性能优化实践",
      "milestones": [
        {"name": "多Agent项目", "done_criteria": "端到端 demo 可运行",
         "tasks": [{"name": "实现双Agent协作 Demo", "priority": "high"}]},
        {"name": "性能优化项目", "done_criteria": "优化前后对比报告",
         "tasks": [{"name": "输出优化前后对比报告", "priority": "medium"}]}
      ]
    },
    {
      "type": "learn",
      "name": "求职准备",
      "goal": "简历与面试就绪",
      "kpi": {"metric": "模拟面试", "target": "连续 2 次通过", "evidence": "模拟记录"},
      "resume_value": "",
      "milestones": [
        {"name": "简历优化", "done_criteria": "ATS 关键词全覆盖且项目量化",
         "tasks": [{"name": "按 JD 关键词重写简历", "priority": "high"}]},
        {"name": "面试题准备", "done_criteria": "高频题能脱稿讲解",
         "tasks": [{"name": "整理并练习高频题", "priority": "high"}]}
      ]
    }
  ]
}')
```

### 4. 任务执行

```
generate_tasks()
get_next_tasks()   # 从返回值中取 task_id
checkin_task(task_id="<get_next_tasks 返回的 ID>", status="completed", notes="多Agent系统学习完成")
```

### 5. 洞察调整（阶段完成后审计）

```
trigger_insight(trigger_type="stage_audit")
apply_insight(insight_json='{
  "trigger_type": "stage_audit",
  "status": "ahead",
  "summary": "进度超前，可以加深难度",
  "insights": ["学习速度超预期", "可以加深难度"],
  "adjustment_needed": true,
  "adjustment_type": "auto",
  "adjustment_reason": "当前任务完成质量高",
  "changes": [{"type": "add_task", "details": {"name": "多Agent系统深入研究"}}],
  "user_message": "进度超前，已为你增加进阶任务"
}')
```

### 用户想要日程表？

直接在对话中把当前阶段的任务写成 markdown/HTML 文档交给用户，
时间块留空由用户自己填——系统不存储日程。
