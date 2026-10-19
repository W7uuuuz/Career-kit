# MCP 工具总览

> 32 个 MCP 工具的唯一事实源。参数细节以各工具 docstring 为准；
> 工作流与前置条件见 [工作流详解](workflow.md)。

## 工具总览

### 建档工具（6）

| 工具 | 作用 |
|------|------|
| `start_session` | 初始化会话，返回欢迎信息与当前档案 |
| `parse_resume` | 解析 PDF / DOCX / MD / TXT 简历，输出待验证素材 |
| `intake` | 逐步填充 `who` / `have` / `want`；技能建议带证据与置信度 |
| `finalize_profile` | 确认档案并生成摘要；技能无确认证据时触发摸排门禁 |
| `import_jd` | 导入目标 JD 文本 |
| `import_jd_file` | 从文件导入目标 JD |

### 档案管理工具（5）

| 工具 | 作用 |
|------|------|
| `list_profiles` | 列出所有档案（身份/目标/版本/当前使用） |
| `switch_profile` | 切换当前档案 |
| `delete_profile` | 回收站式删除（需 `confirm="true"`，可恢复） |
| `list_trash` | 列出回收站中的档案 |
| `restore_profile` | 从回收站恢复档案 |

### 数据获取工具（5）

| 工具 | 作用 |
|------|------|
| `list_data_sources` | 列出可用企业源及各自支持的参数 |
| `get_scraper_guide` | 读取指定企业源的完整使用教程 |
| `fetch_company_jobs` | 抓取真实岗位/面经，自动写入知识库 |
| `fetch_jd_detail` | 获取 JD 全文或面经正文 |
| `search_knowledge` | 检索本地知识库 `~/.career-kit/knowledge/` |

### 分析规划工具（6）

| 工具 | 作用 |
|------|------|
| `explore_goals` | 无目标时三轴定位（能力 × 兴趣 × 真实市场）并提出候选方向 |
| `analyze_gaps` | 返回差距分析方法论上下文 |
| `save_gap_analysis` | 保存分析结果（含内容质量门） |
| `generate_roadmap` | 返回路线图方法论上下文 |
| `save_roadmap` | 保存路线图（起点/层级/届别硬校验，自动生成职业地图） |
| `import_plan` | 导入既有规划文档，对比取舍在对话中完成 |

### 任务执行工具（5）

| 工具 | 作用 |
|------|------|
| `generate_tasks` | 从路线图生成任务；重建时历史进度沉淀为能力证据 |
| `detail_current_phase` | 只细化当前阶段，返回详细路线方法论 |
| `save_current_detail` | 保存当前阶段详细路线（once/daily/percent 打卡点） |
| `get_next_tasks` | 返回当前阶段下一步任务（关卡式） |
| `checkin_task` | 打卡；完成自动沉淀能力证据 |

### 洞察与产出工具（5）

| 工具 | 作用 |
|------|------|
| `trigger_insight` | 触发洞察（仅 `stage_audit` / `event`） |
| `apply_insight` | 应用洞察结果（add/remove/modify 任务） |
| `get_progress` | 查看整体进度 |
| `get_workflow_status` | 工作流状态 + 目标变更检测 |
| `export_dashboard` | 自包含 HTML：`progress` 仪表盘 / `roadmap` 职业地图 |

## 工作流

```
建档 → 分析 → 规划 → 任务执行 → 打卡 → 阶段审计/事件洞察 → 循环
```

## 返回约定

- 所有工具返回字符串；结构化结果为 JSON 字符串。
- 成功结果通常含 `message`、`next_steps`、`context`。
- 错误统一为 `{"isError": true, "code": "...", "message": "...", "details": {...}}`。
- 工具返回的 `next_steps` 是推荐的下一步，优先按提示执行。

## MCP Resources

除工具外，服务器还暴露以下只读文档资源：

| URI | 内容 |
|-----|------|
| `career-kit://docs/llms` | LLM 使用指南 |
| `career-kit://docs/workflow` | 工作流详解 |
| `career-kit://docs/tools` | 本文件 |
| `career-kit://docs/scrapers` | 企业库总览 |
| `career-kit://docs/scrapers/{id}` | 指定企业使用教程 |
| `career-kit://docs/knowledge` | 知识库结构 |
| `career-kit://docs/examples` | 示例目录 |

## 源码位置

| 分类 | 模块 |
|------|------|
| 建档 | `src/tools/session_tools.py` |
| 档案管理 | `src/tools/profile_tools.py` |
| 数据获取 | `src/tools/data_tools.py`、`src/scrapers/` |
| 分析规划 | `src/tools/analysis_tools.py`、`src/tools/roadmap_tools.py` |
| 任务执行 | `src/tools/task_tools.py` |
| 洞察 | `src/tools/insight.py` |
| HTML 渲染 | `src/tools/dashboard.py` |
