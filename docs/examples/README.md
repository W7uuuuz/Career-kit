# 示例目录

> 完整工作流见 [工作流详解](../workflow.md)，工具清单见 [工具总览](../tools.md)。

## 零等待演示

- [demo/](demo/)：一份样例简历经完整链路生成的**可交互职业地图 HTML**
  （双击即看，无需安装）

## 场景示例

- [前端转 AI](scenarios/career_change.md)：前端工程师转行 AI Agent 工程师
- [面试冲刺](scenarios/interview_prep.md)：拿到面试后的准备流程
- [技能升级](scenarios/skill_upgrade.md)：在职人员提升技能

## 示例数据

- [示例档案](data/sample_profile.json)
- [示例差距分析](data/sample_gap.json)
- [示例路线图](data/sample_roadmap.json)

## 最短链路

```
start_session → intake(who/have/want) → finalize_profile
→ fetch_company_jobs → analyze_gaps → save_gap_analysis
→ generate_roadmap → save_roadmap
→ generate_tasks → get_next_tasks → checkin_task
→ export_dashboard
```
