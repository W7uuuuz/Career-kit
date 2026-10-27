# MCP 工具总览

> 40 个 MCP 工具的唯一事实源。参数细节以各工具 docstring 为准；
> 工作流与前置条件见 [工作流详解](workflow.md)。

## 工具总览

### 建档工具（6）

| 工具 | 作用 |
|------|------|
| `start_session` | 初始化会话，返回欢迎信息与当前档案 |
| `parse_resume` | 解析 PDF / DOCX / MD / TXT 简历，输出待验证素材与自评三问 |
| `intake` | 逐步填充 `who` / `have` / `want`；技能带证据 + authorship + control_level 自评，整份自评写 `have.self_assessment` |
| `finalize_profile` | 确认档案并生成摘要；技能无确认证据或缺 authorship/control_level/self_assessment 自评时触发摸排门禁 |
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

### 数据获取工具（9）

| 工具 | 作用 |
|------|------|
| `list_data_sources` | 列出可用企业数据源及各自支持的参数 |
| `get_scraper_guide` | 读取指定企业源的完整使用教程 |
| `fetch_company_jobs` | 抓取真实岗位/面经，自动写入知识库 |
| `fetch_jd_detail` | 获取 JD 全文或面经正文 |
| `search_knowledge` | 检索本地知识库 `~/.career-kit/knowledge/` |
| `search_cases` | 聚合搜寻同背景成功经验与面试要求（本地 + 牛客 + GitHub + 目标企业 JD，学历五档四层归一打分） |
| `research_market` | 返回市场调研方法论与 4 步模板（范围宣告 → 批量抓取 → 报告落地 → 衔接分析） |
| `gather_research_data` | 一次批量抓取：目标公司 1 家 + 对照 2-4 家 JD 与同学历经历案例；逐条补抓详情（无详情的岗位剔除并计入缺口）；返回花名册与聚合摘要；报告 md/html/json 落盘 `~/CareerKit/`，`profile.research` 同步更新；含 BOSS 源须先询问用户并传 `boss_confirmed=true`，未登录返回 `LOGIN_REQUIRED` 由用户决定是否登录 |
| `read_research_details` | 按花名册标识读取调研详情：不传 `ids` 返回花名册、聚合摘要与子 Agent 委派方案（`delegate`，对应 `research-analyst`）；传 `ids` 读取选定条目全文（`kind="jd"` 岗位 / `"case"` 面经与他人路径），单次上限 10 条 |

### 分析规划工具（7）

| 工具 | 作用 |
|------|------|
| `explore_goals` | 无目标时三轴定位（能力 × 兴趣 × 真实市场）并提出候选方向 |
| `analyze_gaps` | 返回差距分析方法论上下文 |
| `save_gap_analysis` | 保存分析结果（含内容质量门） |
| `generate_roadmap` | 返回路线图方法论上下文（6 步工作流；审计为第二意见） |
| `save_roadmap` | 保存路线图（只校验结构；质量项以 `advisories` 返回并持久化，不阻断保存；`force` 已废弃；自动生成职业地图） |
| `save_roadmap_audit` | 审计结果落库（PASS / PASS_WITH_NOTES / FAIL + issues/notes；按 `roadmap_hash` 绑定版本，不阻断定稿） |
| `import_plan` | 导入既有规划文档，对比取舍在对话中完成 |

### 任务执行与求职漏斗工具（7）

| 工具 | 作用 |
|------|------|
| `generate_tasks` | 从路线图生成任务；重建时历史进度沉淀为能力证据 |
| `detail_current_phase` | 只细化当前阶段，返回详细路线方法论 |
| `save_current_detail` | 保存当前阶段详细路线（once/daily/percent 打卡点；phase_id 必须存在于当前路线图） |
| `get_next_tasks` | 返回当前阶段下一步任务（关卡式） |
| `checkin_task` | 打卡；完成自动沉淀能力证据 |
| `record_application` | 记录/更新投递进展（求职漏斗）；重复投递有去重保护 |
| `delete_application` | 删除单条投递记录（录错/重复录入时用，不可恢复） |

### 洞察与产出工具（6）

| 工具 | 作用 |
|------|------|
| `trigger_insight` | 触发洞察（仅 `stage_audit` / `event`）；prompt 内含漏斗归因事实 |
| `apply_insight` | 应用洞察结果（add/remove/modify 任务；stage_audit 时点亮阶段审计标记 `audited_phases`） |
| `get_progress` | 查看整体进度（含求职漏斗与投递清单） |
| `get_weekly_review` | 周检视：周期事实复盘（打卡/阶段/漏斗），days 合法范围 1-90 |
| `get_workflow_status` | 工作流状态 + 目标变更检测 + 换 JD 后差距分析过期提示 + 周检视提示 |
| `export_dashboard` | 自包含 HTML：`progress` 仪表盘（含近 7 天与漏斗卡片）/ `roadmap` 职业地图（无路线图拒绝导出） |

## 工作流

```
建档 → 市场调研 → 分析 → 规划 → 任务执行 → 打卡/投递记录 → 阶段审计/事件洞察/周检视 → 循环
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
| `career-kit://docs/scrapers` | 企业数据源总览 |
| `career-kit://docs/scrapers/{id}` | 指定企业使用教程 |
| `career-kit://docs/knowledge` | 知识库结构 |
| `career-kit://docs/examples` | 示例目录 |

## 源码位置

| 分类 | 模块 |
|------|------|
| 建档 | `src/tools/session_tools.py`（简历解析在 `resume_parser.py`） |
| 档案管理 | `src/tools/profile_tools.py`（领域层 `profile.py`） |
| 数据获取 | `src/tools/data_tools.py`、`src/tools/knowledge_search.py`、`src/scrapers/` |
| 分析规划 | `src/tools/analysis_tools.py`、`src/tools/roadmap_tools.py`（`import_plan` 在 `data_tools.py`） |
| 任务与漏斗 | `src/tools/task_tools.py`、`src/tools/application_tools.py`（领域层 `task_manager.py`、`application_tracker.py`） |
| 洞察与产出 | `src/tools/insight.py`、`src/tools/dashboard.py`（周检视领域层 `review.py`） |
