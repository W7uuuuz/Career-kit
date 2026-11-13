# MCP 工具总览

> 55 个 MCP 工具的唯一事实源。参数细节以各工具 docstring 为准；
> 工作流与前置条件见 [工作流详解](workflow.md)。

## 工具总览

### 建档工具（6）

| 工具 | 作用 |
|------|------|
| `start_session` | 初始化会话，返回欢迎信息与当前档案 |
| `parse_resume` | 解析 PDF / DOCX / MD / TXT 简历，输出待验证素材与自评三问；只登记素材，不跳过 `have` 摸排；识别不到姓名/手机号/邮箱时返回 `missing_fields` 与 `profile_hints`，提示用户补充，不静默留空 |
| `intake` | 逐步填充 `who` / `have` / `want`；技能带证据 + authorship + control_level 自评，整份自评写 `have.self_assessment`；`want` 需用户确认并带 `user_confirmed=true`。`want.job_kind`（intern/campus/social）决定采集通道；`want.exclude_directions` 记录用户明确不投的方向（如「算法」），采集时直接剔除 |
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

### 数据获取工具（11）

| 工具 | 作用 |
|------|------|
| `list_data_sources` | 列出可用企业数据源及各自支持的参数 |
| `get_scraper_guide` | 读取指定企业源的完整使用教程 |
| `boss_login` | 管理 BOSS 直聘登录会话：`status` 只读检查（零副作用，`live=true` 才做后台真实探测）/ `login` 打开可见登录页、用户只扫码，成功后浏览器窗口常驻复用 / `close` 关闭专用浏览器；TTL 唯一来源 `LOGIN_TTL_SECONDS` |
| `fetch_company_jobs` | 抓取真实岗位/面经，自动写入知识库；实习岗位优先 `shixiseng`（转正机会/实习月数/每周天数可核验），BOSS 只作薪资与广度补充 |
| `fetch_jd_detail` | 获取 JD 全文或面经正文 |
| `search_knowledge` | 检索本地知识库 `~/.career-kit/knowledge/` |
| `get_industry_snapshot` | 轻量行业快照（扫盲子流程）：行业地图 + 岗位卡 + 当前招聘样本/薪资 + 相关专业 + 来源/缺口；默认互联网/软件，支持能源动力、电子/半导体/通信、机械/装备、电气/电力、金融 |
| `search_cases` | 聚合搜寻他人经验（牛客/GitHub/本地面经）与企业要求（目标企业 JD/BOSS）；两类卡片分开展示并标注「他人经验」/「企业要求」，本地 JD 来源标为 local |
| `research_market` | 返回市场调研方法论与 4 步模板（范围宣告 → 批量抓取 → 报告落地 → 衔接分析） |
| `gather_research_data` | 一次批量抓取：目标公司 1 家 + 对照 2-4 家 JD 与同学历经历案例；逐条补抓详情（无详情的岗位剔除并计入缺口）；按 `want.job_kind` 做通道路由，不服务目标通道的源标记 `skipped`（不计失败）；补详情后按资格谓词（届别/学历/招聘类型/城市/排除方向）二次筛选，不合格岗位不进样本并按原因计数；单源超时默认 25 秒，可用 `source_timeout` 或 `CAREER_KIT_RESEARCH_SOURCE_TIMEOUT` 配置，单源失败自动重试 1 次；断点缓存按「来源 + 查询」续抓；源维度每源只保留一个最终状态（ok/empty/skipped/failed），过滤/剔除按条目维度聚合且保留标题与原因；抽取届别/学历下限/每周天数/实习月数等硬门槛字段（抽不到留空）；岗位来源集中度过高时给出单一来源风险与已注册替代源建议；面经全文在调研时落盘；`max_sources` 默认 4，源过多时只跑前 N 个并返回 `batch.deferred_specs` 与续跑提示，避免一次请求超时；返回 `summary` 关键结论（岗位/案例数、高频技能、城市、薪资、状态）与花名册；报告 md/json 落盘 `~/CareerKit/`，`profile.research` 同步更新；含 BOSS 源只问一次并传 `boss_confirmed=true`；确认但未登录返回 `ACTION_REQUIRED` / `next_tool=boss_login`，直接调用 `boss_login(action="login")`（用户只扫码），不再追问第二次 |
| `read_research_details` | 按花名册标识读取调研详情：不传 `ids` 返回花名册、聚合摘要与子 Agent 委派方案（`delegate`，对应 `research-analyst`）；传 `ids` 读取选定条目全文（`kind="jd"` 岗位 / `"case"` 面经与他人路径），单次上限 10 条；读取本地已落盘内容，零网络请求，未落盘的案例会明确标注 |

### 证据引用工具（2）

| 工具 | 作用 |
|------|------|
| `record_claim` | 记录一条可引用结论：事实必须有来源（url/name），从业者经验必须写 source.name 与 scope；可带 limitation 与 expires_at。数字结论先记录再引用 |
| `list_claims` | 列出已记录的结论，按内容/来源/范围过滤；生成路线图前用它确认可引用的证据 |

### 分析规划工具（7）

| 工具 | 作用 |
|------|------|
| `explore_goals` | 无目标时三轴定位（能力 × 兴趣 × 真实市场）并提出候选方向 |
| `analyze_gaps` | 返回差距分析方法论上下文 |
| `save_gap_analysis` | 保存分析结果；`skill_gaps` 非空时每项必须有 `skill` 与 `source`，缺失返回 `INVALID_PARAM` 且不写档案；空列表允许保存并给建议；质量建议持久化到档案。市场调研被跳过时仍写 `GapReport`：`market_baseline_id=""`、`meta.validation.market_skipped=true`、`meta.inputs.target_spec_id` 指向当前 `TargetSpec`；缺 ProfileSnapshot/TargetSpec 不写半成品 |
| `generate_roadmap` | 返回路线图方法论上下文（6 步工作流；审计为第二意见）；附带证据包（claims / 案例 / JD 样本 / 缺口）与四类必查证据（通道、转正风险、同背景门槛、校招时间窗） |
| `save_roadmap` | 保存路线图（只校验结构；质量项以 `advisories` 返回并持久化，不阻断保存；`force` 已废弃；自动生成实时职业地图）。新增通道现实建议：单通道、无保底、转正未标风险、缺时间窗、无引用数字、引用不存在/过期。路线图内容变化导致审计过期时返回 `audit_required=true`、`context.audit.required` 与 `expected_roadmap_hash`，定稿前必须重新审计。市场跳过时写 `BaselinePlan.meta.validation.market_skipped=true`；`import_plan` 后无 `GapReport` 时写 `validation.imported=true`、`gap_report_id=""` |
| `save_roadmap_audit` | 审计结果落库（PASS / PASS_WITH_NOTES / FAIL + issues/notes；按 `roadmap_hash` 绑定版本，不阻断定稿） |
| `import_plan` | 导入既有规划文档，对比取舍在对话中完成；设置 `guidance.plan_imported_at` 并提示用 `save_roadmap` 保存结构化路线图 |

### 草稿工具（4）

长内容（差距分析、路线图等）先分片写入草稿，再把 `draft_id` 传给对应的 `save_*` 工具，避免单个 JSON 参数被传输层截断。

| 工具 | 作用 |
|------|------|
| `draft_create` | 创建草稿，返回 `draft_id`；`kind` 用于标记用途（如 gap/roadmap） |
| `draft_append` | 向草稿追加一段内容（建议每片 <=2KB）；累计超过 2MB 时拒绝 |
| `draft_status` | 查看草稿字节数、片段数与 JSON 是否已闭合 |
| `draft_clear` | 删除草稿（保存成功后自动清理，失败或放弃时手动清理） |

### 企业适配工具（7）

| 工具 | 作用 |
|------|------|
| `select_target_companies` | 阶段 6：按目标档/过渡档/行业筛选企业池；支持 include/exclude；`selected_ids` 可从推荐池中挑出用户真正关注的子集（allowlist，优先级高于 include），命中企业保留、未命中企业 excluded，并落库到 `meta.validation.selected_ids`；未确认只生成推荐池，确认后才能进入采集。显式参数优先于 TargetSpec 与档案默认值；身份字段只能填充 TargetSpec 空字段，双方均有值且冲突时拒绝落库。档位参数同时用于 `target_spec` 回显、`counts/by_tier` 统计与企业池，保证同一份数据只有一套档位口径 |
| `collect_company_evidence` | 阶段 7：批量抓取目标企业 JD 与面经，按 TargetSpec 的 role（为空回退 direction）向各源透传关键词，只传该源 `PARAMS` 支持的参数；按 `TargetSpec.job_kind` 做通道路由（如 `scope=intern`），不服务目标通道的源标记 `skipped` 而非失败；完整岗位名含斜杠/括号/招聘类型时自动拆出主关键词；补详情后按资格谓词（届别/学历/招聘类型/城市/排除方向）筛选，不合格岗位不进样本并按原因计入 gaps；源「无匹配」为 `empty`，只有超时/异常才计 `failed`；接口异常转成可读原因并保留技术细节。支持 `company_ids` 限定企业、`batch_size`（默认 3）分批、以及检查点自动续跑：未完成时返回 `status="partial"` 与已采企业进度，再次调用默认续跑，已完成企业不重复抓取。城市硬筛、详情补抓、去重；目标城市非空时 location 为空的岗位按硬筛剔除，并计入 `unknown_city` 与 `dropped_city`；单源失败不拖垮整批；复用样本标注来源轮次与所属企业池，池外复用默认丢弃，仅 `include_outside_pool=true` 时保留并单独计数；产物落盘证据池报告，返回 `summary` 与 `batch` 进度摘要；可选 `include_boss=true` 补充 BOSS 薪资与广度（需先确认并扫码登录）。BOSS 的 `detail_status=list_only` 仅豁免详情补抓/详情缺失剔除，不豁免城市硬筛：空 location 的 list-only 行按城市剔除并计入 `dropped_city`、`unknown_city` 与 list-only 缺口；保留的 list-only 行只保留列表字段 |
| `analyze_company_requirements` | 阶段 8：聚合前按用户学历/届别/经验与 JD 字段做硬门槛预筛，被筛样本进入 `excluded_jd` 与 gaps，不参与高频词统计；档案字段缺失时只标注缺失、不猜测。用代码统计 JD/面经频率、公司覆盖、Wilson 区间与逐条硬门槛，返回受约束的分析提示；样本不足时返回具体 `supplement_targets`（池内无 JD / 缺 requirements 的企业）与 `supplement_actions`；失败时返回 `code` 与「可先按基线执行」的 `skip_option`；只落「草稿」artifact，置信度只按样本量计算 |
| `save_requirement_profile` | 阶段 8：保存 LLM 的定性解读并标记需求画像为已保存；未保存或其他没有非空 interpretation 的草稿不得进入阶段 9；必须能从 EvidenceRun 复算统计，缺失或损坏时拒绝落库；数字、列表与 evidence_ids 由代码重算，interpretation 一旦引用证据 id 必须真实存在 |
| `plan_execution_alignment` | 阶段 9：返回校准方法论、基线路线图、已完成能力与需求摘要，供设计执行版方案；RequirementProfile 必须 saved 或 interpretation 非空（D5 OR），两者都没有时拒绝；基线读取自 BaselinePlan artifact |
| `save_execution_alignment` | 阶段 9：预览或应用执行版；RequirementProfile 必须 saved（validation 存在且 status 非 draft）或 interpretation 非空（D5 OR），两者都没有时拒绝预览/应用；ExecutionPlan 必须引用当前 `baseline_plan_id` 与 `requirement_profile_id`，基线来自真实 BaselinePlan artifact 且 `profile.plan` 与 artifact roadmap 一致，显式传入的 baseline_plan_id 不一致、artifact 缺失或 profile.plan 分叉都拒绝落库；无 BaselinePlan 返回 `MISSING_BASELINE_PLAN`，不写已应用 artifact；每条变更必须带非空 evidence_ids 且属于当前 RequirementProfile，未知或空 id 拒绝落库；确认后替换计划、保留完成历史并记录调整 |
| `check_plan_fit` | 计划失配检测：只读检查证据新鲜度、链路一致性、要求覆盖率与漏斗信号，返回给用户的询问话术；不自动改计划 |

### 任务执行与求职漏斗工具（8）

| 工具 | 作用 |
|------|------|
| `generate_tasks` | 只从路线图生成当前阶段任务（后续阶段保留里程碑），并自动刷新实时职业地图；重建时历史进度沉淀为能力证据；阶段 KPI 与任务名都带计数且任务未显式配置打卡时，自动补 `checkin_mode="daily"` 与 `checkin_goal`，让 KPI 能在任务层累计 |
| `detail_current_phase` | 只细化当前阶段：返回方法论 + 资源目录；任务需带 how_to / resources / done_criteria 与打卡点 |
| `save_current_detail` | 保存当前阶段详细路线（once/daily/percent 打卡点；phase_id 必须存在于当前路线图） |
| `get_next_tasks` | 返回当前阶段下一步任务（关卡式） |
| `checkin_task` | 打卡；完成自动沉淀能力证据 |
| `build_application_list` | 从证据池批量筛选投递岗位：城市硬筛（目标城市非空时 location 为空的岗位剔除并计入未知城市缺口）、方向/技能/学历/档位打分、排除已投递；生成投递清单报告并写入 ApplicationState.candidates |
| `record_application` | 记录/更新投递进展（求职漏斗）；重复投递有去重保护 |
| `delete_application` | 删除单条投递记录（录错/重复录入时用，不可恢复） |

### 洞察与产出工具（5）

| 工具 | 作用 |
|------|------|
| `trigger_insight` | 触发洞察（仅 `stage_audit` / `event`）；prompt 内含漏斗归因事实 |
| `apply_insight` | 应用洞察结果（add/remove/modify 任务；stage_audit 时点亮阶段审计标记 `audited_phases`） |
| `get_progress` | 查看整体进度（含求职漏斗与投递清单） |
| `get_weekly_review` | 周检视：周期事实复盘（打卡/阶段/漏斗），days 合法范围 1-90 |
| `get_workflow_status` | 工作流状态 + 目标变更检测 + 换 JD 后差距分析过期提示 + 周检视提示 |

## 工作流

```
1 职业档案构建 → 2 目标岗位定位 → 3 市场基线调研 → 4 能力差距诊断
→ 5 培养方案规划 → 6 目标企业筛选 → 7 岗位与面经采集 → 8 企业需求分析
→ 9 执行方案校准 → 10 任务执行与打卡 → 11 求职投递管理（含投递清单）
→ 12 周期复盘与计划调整 → 循环
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
| `career-kit://docs/rules` | 档位含义、评分口径、打卡方式、数据边界 |
| `career-kit://docs/examples` | 示例目录 |
| `career-kit://docs/prompts/onboarding` | 开场路由 |
| `career-kit://docs/prompts/quick-scan` | 行业扫盲子流程 |
| `career-kit://docs/prompts/grounding` | 数据边界 |

同时注册 3 个 MCP Prompt：`career-onboarding`、`career-quick-scan`、`career-grounding`。

## 源码位置

| 分类 | 模块 |
|------|------|
| 建档 | `src/tools/session_tools.py`（简历解析在 `resume_parser.py`） |
| 档案管理 | `src/tools/profile_tools.py`（领域层 `profile.py`） |
| 数据获取 | `src/tools/data_tools.py`、`src/tools/boss_tools.py`、`src/tools/knowledge_search.py`、`src/tools/research_tools.py`、`src/tools/case_tools.py`、`src/scrapers/` |
| 分析规划 | `src/tools/analysis_tools.py`、`src/tools/roadmap_tools.py`、`src/tools/claim_tools.py`、`src/tools/resource_catalog.py`（`import_plan` 在 `data_tools.py`） |
| 企业适配 | `src/tools/company_selection_tools.py`、`src/tools/evidence_tools.py`、`src/tools/requirement_tools.py`、`src/tools/execution_plan_tools.py`、`src/tools/plan_fit_tools.py`（领域层 `src/core/`） |
| 任务与漏斗 | `src/tools/task_tools.py`、`src/tools/application_tools.py`、`src/tools/application_list_tools.py`（领域层 `task_manager.py`、`application_tracker.py`） |
| 洞察与产出 | `src/tools/insight.py`、`src/tools/dashboard.py`、`src/tools/industry_tools.py`（周检视领域层 `review.py`） |

