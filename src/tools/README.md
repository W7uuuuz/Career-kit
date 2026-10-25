# MCP 工具

32 个工具，分六类。完整清单、参数与调用时机以
[docs/tools.md](../../docs/tools.md) 为唯一事实源；本文件只保留模块索引，避免重复维护。

| 分类 | 数量 | 模块 |
|------|------|------|
| 建档 | 6 | `session_tools.py`（简历解析 `resume_parser.py`） |
| 档案管理 | 5 | `profile_tools.py`（领域层 `profile.py`） |
| 数据获取 | 5 | `data_tools.py`、`knowledge_search.py`、`src/scrapers/` |
| 分析规划 | 6 | `analysis_tools.py`、`roadmap_tools.py`（`import_plan` 在 `data_tools.py`） |
| 任务执行 | 5 | `task_tools.py`（领域层 `task_manager.py`） |
| 洞察与产出 | 5 | `insight.py`、`dashboard.py` |

工作流见 [docs/workflow.md](../../docs/workflow.md)，LLM 运行时手册见
[docs/llms.txt](../../docs/llms.txt)。
