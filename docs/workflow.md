# 工作流详解

> 各阶段的目标、前置条件、流程与输出。工具清单见 [tools.md](tools.md)。

核心理念：**顺序归产品，时间归用户**——不为任务设定时限。

## 工作流总览

```
建档 → 市场调研 → 分析 → 规划 → 任务执行 → 打卡/投递记录 → 阶段审计/事件洞察/周检视 → 循环
```

---

## 阶段 1：建档

**目标**：建立档案，摸清真实水平（简历有美化成分，包括 AI 写的代码——作者身份要说清）。

**前置条件**：无。

**流程**：

```
1. start_session()
2. parse_resume(file_path)   # 可选：解析简历素材；随后「求证 + 自评三问」同轮完成
3. intake(who)      # 姓名、教育、当前状态；缺毕业年份时补 graduation_year
4. intake(have)     # 技能、经历、资源；每条技能带 evidence + verified + authorship
                    # （self_written/ai_assisted/ai_generated/referenced）
                    # + control_level（0-10：3=讲架构，6=逐行讲清，8+=手写），
                    # 整份自评写 have.self_assessment（resume_trust + notes）
5. 确定目标：
   - 有明确目标 → intake(want)
   - 方向模糊 → explore_goals() → 对话选定 → intake(want)
   - 有 JD 文件 → import_jd_file() / import_jd()
6. finalize_profile()
```

> 摸排硬门禁：技能无用户确认证据，或缺 authorship/control_level/
> self_assessment 自评时，finalize 与 analyze_gaps 都会拒绝放行；
> authorship/control_level 必须来自用户本人回答，AI 不得代填；
> 唯一跳过方式是用户明确要求时 `finalize_profile(skip_probing=True)`（留痕）。

**输出**：

- `profile.summary`：档案摘要
- `profile.section_updated_at`：目标变更检测依据

**关键规则**：

- 技能必须经过用户确认，简历原文不能直接当证据（门禁细节见上方「摸排硬门禁」）

---

## 阶段 2：市场调研（核心卖点「来源真实」）

**目标**：抓取真实市场事实，生成可查证的调研报告——后续分析的地基。

**前置条件**：`finalize_profile` 已调用（推荐；无调研也可直接分析，只是软提示）。

**流程**：

```
1. research_market()                              # 调研方法论与 4 步模板
2. 向用户播报调研菜单（抓哪家、约半分钟、报告落在哪），宣告即执行
3. 名单含 BOSS 时先问用户「是否抓取 BOSS 直聘（需扫码登录）」，
   同意后在下一步传 boss_confirmed=true
4. gather_research_data(jd_specs, case_query, boss_confirmed)
   - jd_specs：目标公司 1 家 + 同方向对照 2-4 家（优先含薪来源如 BOSS）
   - case_query：role + education（五档四层写法如「双非本」）+ company/city
   - 逐条补抓岗位详情（无详情岗位剔除并计入数据缺口）
   - 返回 CONFIRMATION_REQUIRED / LOGIN_REQUIRED 时把问题转问用户并等待答复，
     不得静默跳过 BOSS 或直接宣布调研失败
5. 报告三件套自动落盘（代码渲染，不经 LLM），向用户汇报三要素
6. 按需读取全文：从花名册中选择 3-5 条，调用 read_research_details(ids=..., kind="jd"/"case")；
   宿主 harness 支持子 Agent 时，用 Task 发起 research-analyst（仓库提供
   `.opencode/agent/research-analyst.md` 与 `.claude/agents/research-analyst.md`），
   把花名册、聚合摘要与 `delegate.prompt` 交给它，由它返回结论与重点名单
7. 用户确认后进入差距分析
```

**输出**：

- 报告三件套：`~/CareerKit/<档案>/调研报告/<日期_方向>.{md,html,json}`
- `profile.research`：`{generated_at, direction, report_md, report_html, report_json,
  index, jd_samples, cases, source_status, gaps, digest, counts}`
  ——差距分析与路线图直接引用；岗位全文仅存于档案/报告/json，不进入模型上下文
- 资产总览入口：`~/CareerKit/index.html`

**关键规则**：

1. 报告内容 100% 代码渲染自抓取数据，不经 LLM——「来源真实」的硬保证
2. 每条岗位/案例带来源链接、来源平台、抓取时间，用户可逐条点开验证
3. 岗位详情必抓：未取得详情的岗位不纳入报告，并在数据缺口如实说明
4. 花名册优先：工具返回「花名册（标识与摘要）+ 聚合摘要」，不一次性注入岗位正文；
   读取全文时选取 3-5 条；宿主 harness 支持子 Agent 时，用 Task 发起 research-analyst，
   父 Agent 按 `delegate` 方案委派并汇总结论与重点名单
5. BOSS 直聘需扫码登录：抓取前必须询问用户；工具返回 `CONFIRMATION_REQUIRED`
   （尚未确认）/ `LOGIN_REQUIRED`（尚未登录）时先询问用户，不得静默跳过或直接判定失败
6. 任一源失败不中断，失败原因进报告「来源状态面板」如实展示；
   未获取的内容明确写「未获取」，绝不编造
7. 全部失败时返回 `MISSING_DATA` 并引导 `import_jd` / `import_jd_file`，不生成空报告
8. 多次调研分别留档（文件名含日期与方向），不覆盖既有报告
9. 汇报口径：样本数与来源成败 → 报告完整路径 → 下一步；解读留给差距分析

---

## 阶段 3：分析

**目标**：基于真实市场数据找出差距。

**前置条件**：`finalize_profile` 已调用。

**流程**：

```
1. 优先引用调研：profile.research 有报告时，先 read_research_details() 获取花名册与
   聚合摘要，选取 3-5 条读取全文（标注来源）；不一次性注入全量正文
2. 无调研时软提示（建议先走阶段 2 市场调研），用户同意后再按以下数据链路补充
3. list_data_sources()                         # 查看可用源与参数
4. get_scraper_guide(company)                  # 首次使用前读取教程
5. fetch_company_jobs(company, params)         # 真实岗位/面经
6. fetch_jd_detail(url)                        # 需要的 JD 全文
7. search_knowledge(query)                     # 本地已积累资料
8. search_cases(role, education, company)      # 定向补充同背景案例兜底
9. analyze_gaps()
10. save_gap_analysis(gap_json)
```

**输出**：

- `profile.gap`：`match_score`（0-100）、`skill_gaps`、`priority_actions`、
  `resume_red_flags`、`start_level` 等

**关键规则**：

1. 分析前必须基于真实数据；无数据时引导用户导入 JD，绝不编造
2. 有调研报告直接引用（不重复全量抓取）；案例卡片展示时标明来源
3. 过程透明（硬纪律）：`analyze_gaps` 返回 4 步 step_template（现状盘点 → 读取调研 →
   两维分析 → 结果预览），每步产出用户看得见的中间结果；
   调用工具前先播报该步在干什么，落盘前用户确认；所有表格必须带「为什么」
4. `skill_gaps` 建议标注 `source`（缺少时给 advisory，不阻断保存）
5. `resume_red_flags` 建议带 `signal` / `risk` / `evidence_fix`；AI 作者身份提示为
   advisory，由 LLM 与用户判断是否需要补充
6. 薪资行情从岗位搜索结果的 `salary` 字段汇总（同时保留区间上下界）

---

## 阶段 4：规划

**目标**：基于差距生成分阶段路线图，只定顺序与完成标准。

**前置条件**：`profile.gap` 已生成。

**流程**：

```
1. generate_roadmap()
2. save_roadmap(roadmap_json)                        # 先保存（结构校验通过即可）
3. career-roadmap-auditor 审计 → save_roadmap_audit(audit_json)   # 第二意见，不阻断
4. 按需修正后再次 save_roadmap；审计记录按内容哈希标记过期
```

`generate_roadmap` 返回 6 步 step_template（起点判定 → 目标拆解 → 阶段序列 → 逐阶段细化 →
审计（第二意见） → 定稿交付），checkpoint 步必须把中间产物展示给用户确认；
每个表格/清单必须给出「为什么这么拆」的依据。
`save_roadmap` 只做结构校验，始终允许保存：层级跨度、KPI、届别、可执行性等以
`advisories` 返回并持久化，由 LLM、审计员与用户决定是否调整；`force` 参数已废弃。
层级是命中率参考，不是准入许可：跨级不禁止，建议说明证据（作品集/内推/前序交付）；
`start_level_after` 只影响后续阶段的参考，不再写回 `gap.start_level`。
审计输出 `PASS / PASS_WITH_NOTES / FAIL`，FAIL 只用于硬矛盾（编造 JD、无依据跨级、
KPI 完全缺失、届别硬冲突、任务不可打卡），最多 3 条 must_fix，其余进 notes。
审计记录保存在 `profile.audit`，按 `roadmap_hash` 与路线图版本绑定；内容变化后标记过期。
定稿后自动生成路线图 HTML 活地图——交付前先向用户解释它的用途与用法。

已有规划文档时，先 `import_plan(file_path)` 导入，在对话中对比取舍后再保存为路线图。

**输出**：

- `profile.plan.roadmap`：阶段列表（id 规范化为 `phase_N`）
- 每阶段含 `name`、`goal`、`kpi`、`resume_value`、`milestones`；
  `target_level` / `start_level_after` / `graduation_year` / `condition`、
  `access_path` / `evidence_gate` 均为可选参考
- 任务 schema：`{name, description, priority}`，不含任何时长字段
- `profile.audit`：审计轮次、verdict、issues/notes、roadmap_hash
- `save_roadmap` 定稿时自动生成可交互职业地图

**关键规则**：

1. 产品不排期：任务名尽量不带时间节奏词；带时长描述只作建议
2. 里程碑建议有 `done_criteria`；KPI 尽量可验证（投递/进面/PR/题数等）
3. JD 细节必须有真实数据，否则留空并标 `jd_status=pending_user_import`；
   有调研报告时优先引用 `profile.research` 的真实样本
4. 层级只作参考：跨级不禁止，建议说明依据；复评升级不写回差距分析
5. 审计是第二意见：不阻断定稿；FAIL 只用于硬矛盾，最多 3 条 must_fix
6. 换了目标 JD（`import_jd` / `import_jd_file`）后差距分析标记过期，
   必须先重新 `analyze_gaps` 再生成路线图

---

## 阶段 5：任务执行与打卡

**目标**：把路线图转成可执行任务，关卡式推进。

**前置条件**：`profile.plan.roadmap` 已生成。

**流程**：

```
1. generate_tasks()
2. detail_current_phase()              # 只细化当前阶段
3. save_current_detail(detail_json)    # once / daily / percent
4. generate_tasks()                    # 合并打卡点
5. get_next_tasks()
6. checkin_task(task_id, status, notes, amount)
```

**输出**：

- `profile.tasks`：任务列表
- `profile.plan.current_detail`：当前阶段详细路线
- `profile.have.capability_evidence`：完成任务自动沉淀

**投递记录（求职漏斗）**：

```
record_application(company, role, status, ...)   # 新建/更新投递记录
```

- 用户口述「投了 X 公司」→ 新建；「进面试了/挂了/拿 offer」→ 传 `application_id` 更新状态
- 同公司+同岗位的活跃记录不重复新建（返回现有 `application_id`）
- 转化率按**事件历史**统计：面试后被拒仍计入面试数；样本 <5 时转化率降级为参考
- 进面试/拿 offer 是重大事件：按返回值提示触发 `trigger_insight(event)`

**关键规则**：

- `checkin_mode`：`once`（默认）/ `daily`（`amount` 累加天数）/
  `percent`（`amount` 累加完成比例）
- 完成得轻松时可在对话中建议加深，但不自动繁殖任务
- 只记录用户口述的投递事实；不编造、不代用户「估计」状态

---

## 阶段 6：洞察调整与周检视

**目标**：阶段完成后审计，用户报告事件时重估计划，定期周检视复盘。

**前置条件**：`profile.tasks` 已生成。

**流程**：

```
1. trigger_insight(trigger_type="stage_audit" | "event", event_description)
2. apply_insight(insight_json)
3. get_weekly_review(days=7)          # 周期事实复盘（打卡/阶段/漏斗）
```

**输出**：

- `profile.adjustments`：调整记录
- `profile.audited_phases`：已审计阶段（每阶段只审计一次）
- 周检视为 Markdown，可在对话中直接交付或存档；调用后记录 `last_review_at`

| 类型 | 触发时机 | 示例 |
|------|----------|------|
| `stage_audit` | 完成阶段后 | 完成实习后评估含金量 |
| `event` | 用户报告事件 | 拿到大厂面试 / 拿到 offer（可由 record_application 软提示联动） |
| `get_weekly_review` | 定期或久未打卡时 | get_workflow_status 在距上次打卡/上次检视 ≥7 天时提示 |

> 「主动检查 / 超期压缩」已移除——产品不为任务设定时限。
> 周检视只陈述事实（如「距上次打卡 N 天」），不判定超期、不催促。

**洞察输入的漏斗归因**：`trigger_insight` 的 prompt 内含求职漏斗事实——
过筛率低（样本足够）归因简历、面试转化低归因面试准备、零投递归因执行；
漏斗样本 <5 时不下转化结论。

---

## 档案管理

多档案场景（一台电脑多人使用、转行前后多份规划）：

| 工具 | 作用 |
|------|------|
| `list_profiles` | 列出所有档案 |
| `switch_profile` | 切换当前档案 |
| `delete_profile` | 回收站式删除（需 `confirm="true"`，可恢复） |
| `list_trash` | 查看回收站 |
| `restore_profile` | 从回收站恢复 |

---

## 产出与状态

用户资产统一落 `~/CareerKit/`（`CAREER_KIT_ASSETS_DIR` 可覆盖）：`index.html`
是总入口，调研报告按 `<日期_方向>` 留档，路线图与仪表盘用固定文件名。

| 工具 | 产出 |
|------|------|
| `get_progress` | 整体进度（含求职漏斗与投递清单） |
| `get_workflow_status` | 当前阶段（含 research）+ 下一步 + 目标变更检测 + 周检视提示 |
| `get_weekly_review` | 周检视 Markdown（打卡/阶段/漏斗 + 规则化建议） |
| `export_dashboard("progress")` | 进度仪表盘 → `~/CareerKit/<档案>/进度/进度仪表盘.html`（含近 7 天与漏斗卡片） |
| `export_dashboard("roadmap")` | 可交互职业地图 → `~/CareerKit/<档案>/路线图/路线图.html` |

日程表不存储：用户需要时，LLM 在对话中直接写 markdown/HTML，时间由用户自己填。
