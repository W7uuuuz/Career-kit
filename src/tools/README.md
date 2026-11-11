# MCP 工具

51 个工具，分八类。完整清单、参数与调用时机以
[docs/tools.md](../../docs/tools.md) 为唯一事实源；本文件只保留模块索引，避免重复维护。

| 分类 | 数量 | 模块 |
|------|------|------|
| 建档 | 6 | `session_tools.py`（简历解析 `resume_parser.py`） |
| 档案管理 | 5 | `profile_tools.py`（领域层 `profile.py`） |
| 数据获取 | 11 | `data_tools.py`、`boss_tools.py`、`knowledge_search.py`、`research_tools.py`、`case_tools.py`、`src/scrapers/` |
| 证据引用 | 2 | `claim_tools.py` |
| 分析规划 | 7 | `analysis_tools.py`、`roadmap_tools.py`（`import_plan` 在 `data_tools.py`） |
| 企业适配 | 7 | `company_selection_tools.py`、`evidence_tools.py`、`requirement_tools.py`、`execution_plan_tools.py`、`plan_fit_tools.py`（领域层 `src/core/`） |
| 任务执行与漏斗 | 8 | `task_tools.py`、`application_tools.py`、`application_list_tools.py`（领域层 `task_manager.py`、`application_tracker.py`） |
| 洞察与产出 | 6 | `insight.py`、`dashboard.py`、`industry_tools.py`（周检视领域层 `review.py`） |

工作流见 [docs/workflow.md](../../docs/workflow.md)，LLM 运行时手册见
[docs/llms.txt](../../docs/llms.txt)。
