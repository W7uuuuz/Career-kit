# 文档地图

> 唯一入口。公开文档在 `docs/` 根目录（MCP Resources 直接读取），内部开发文档在
> `docs/internal/`（被 `.gitignore` 排除，不随开源仓库发布）。

## 公开文档

| 文档 | 内容 | 主要读者 |
|------|------|----------|
| [llms.txt](llms.txt) | LLM 运行时操作手册：规则、工作流、反模式 | 接入的 AI Agent |
| [workflow.md](workflow.md) | 各阶段前置条件、流程、输入输出 | 使用者 / LLM |
| [tools.md](tools.md) | 41 个 MCP 工具的唯一事实源 | 使用者 / 贡献者 |
| [scrapers.md](scrapers.md) | 已收录企业数据源与贡献流程 | 使用者 / 贡献者 |
| [knowledge.md](knowledge.md) | 本地知识库目录与文件格式 | 使用者 |
| [rules.md](rules.md) | 档位含义、评分口径、打卡方式、数据边界 | 使用者 / LLM |
| [industry-outcomes.md](industry-outcomes.md) | 同行业/相关专业去向数据接入格式 | 使用者 / 贡献者 |
| [prompts/](prompts/onboarding.md) | 开场路由、扫盲子流程、grounding Prompt | LLM / 贡献者 |
| [examples/](examples/README.md) | 可交互职业地图、场景示例、示例数据 | 使用者 |

企业教程的唯一事实源是 `src/scrapers/<id>/guide.md`（`get_scraper_guide` 与
MCP Resource 同源）。

## 内部文档（不发布）

本地开发文档统一放在 `docs/internal/`（被 `.gitignore` 排除，不随开源仓库发布）：
架构、产品设计、实现路径与待办、调研记录、手工 E2E 验证手册。
维护者本地可直接查看，不在公开文档中列出链接。

## 根目录文件

- [README.md](../README.md)：安装、注册、快速开始
- [README.en.md](../README.en.md)：English README
- [llms.txt](../llms.txt)：仓库级 LLM 入口索引（llmstxt 约定）
- [CONTRIBUTING.md](../CONTRIBUTING.md)：贡献流程与开发规范
- [CODE_OF_CONDUCT.md](../CODE_OF_CONDUCT.md)：贡献者行为准则
- [DISCLAIMER.md](../DISCLAIMER.md)：数据源、抓取与责任边界
- [SECURITY.md](../SECURITY.md)：安全问题报告流程

## 维护约定

1. 工具清单只改 `docs/tools.md`；企业教程只改 `src/scrapers/<id>/guide.md`。
2. 工作流只改 `docs/workflow.md`；`docs/llms.txt` 引用它，不重复定义。
3. 内部状态（Phase / 待办 / 已完成）只改 `docs/internal/roadmap.md`。
4. 新增公开文档前先判断能否并入现有文档，避免再次产生重复源。
