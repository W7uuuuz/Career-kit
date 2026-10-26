# 工作流详解

> 各阶段的目标、前置条件、流程与输出。工具清单见 [tools.md](tools.md)。

核心理念：**顺序归产品，时间归用户**——不为任务设定时限。

## 工作流总览

```
建档 → 分析 → 规划 → 任务执行 → 打卡/投递记录 → 阶段审计/事件洞察/周检视 → 循环
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

## 阶段 2：分析

**目标**：基于真实市场数据找出差距。

**前置条件**：`finalize_profile` 已调用。

**流程**：

```
1. list_data_sources()                         # 查看可用源与参数
2. get_scraper_guide(company)                  # 首次使用前读取教程
3. fetch_company_jobs(company, params)         # 真实岗位/面经
4. fetch_jd_detail(url)                        # 需要的 JD 全文
5. search_knowledge(query)                     # 本地已积累资料
6. analyze_gaps()
7. save_gap_analysis(gap_json)
```

**输出**：

- `profile.gap`：`match_score`（0-100）、`skill_gaps`、`priority_actions`、
  `resume_red_flags`、`start_level` 等

**关键规则**：

1. 分析前必须抓取或检索真实数据；无数据时引导用户导入 JD
2. 同背景案例从本地知识库（`search_knowledge`）与 JD 详情/面经中搜寻，展示案例卡片时标明来源
3. 过程透明（硬纪律）：`analyze_gaps` 返回 4 步 step_template（现状盘点 → 案例搜寻 →
   两维分析 → 结果预览），每步产出用户看得见的中间结果；
   调用工具前先播报该步在干什么，落盘前用户确认；所有表格必须带「为什么」
4. 每个 `skill_gaps` 条目必须标注 `source`
5. 每条 `resume_red_flags` 必须带 `signal` / `risk` / `evidence_fix`
6. 薪资行情从岗位搜索结果的 `salary` 字段汇总

---

## 阶段 3：规划

**目标**：基于差距生成分阶段路线图，只定顺序与完成标准。

**前置条件**：`profile.gap` 已生成。

**流程**：

```
1. generate_roadmap()
2. save_roadmap(roadmap_json)
```

`generate_roadmap` 返回 6 步 step_template（起点判定 → 目标拆解 → 阶段序列 → 逐阶段细化 →
审计 → 定稿交付），checkpoint 步必须把中间产物展示给用户确认；
每个表格/清单必须给出「为什么这么拆」的依据。
`save_roadmap` 定稿后自动生成路线图 HTML 活地图——交付前先向用户解释它的用途与用法。

已有规划文档时，先 `import_plan(file_path)` 导入，在对话中对比取舍后再保存为路线图。

**输出**：

- `profile.plan.roadmap`：阶段列表（id 规范化为 `phase_N`）
- 每阶段含 `name`、`goal`、`kpi`、`resume_value`、`milestones`
- 任务 schema：`{name, description, priority}`，不含任何时长字段
- `save_roadmap` 定稿时自动生成可交互职业地图

**关键规则**：

1. 禁止 `duration` / `estimated_days` 等时长字段
2. 里程碑必须有 `done_criteria`
3. JD 细节必须有真实数据，否则留空并标 `jd_status=pending_user_import`
4. 起点层级取 `gap.start_level`；目标超起点时插入过渡阶段

---

## 阶段 4：任务执行与打卡

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

## 阶段 5：洞察调整与周检视

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

| 工具 | 产出 |
|------|------|
| `get_progress` | 整体进度（含求职漏斗与投递清单） |
| `get_workflow_status` | 当前阶段 + 下一步 + 目标变更检测 + 周检视提示 |
| `get_weekly_review` | 周检视 Markdown（打卡/阶段/漏斗 + 规则化建议） |
| `export_dashboard("progress")` | 自包含进度仪表盘（含近 7 天与漏斗卡片） |
| `export_dashboard("roadmap")` | 可交互职业地图 |

日程表不存储：用户需要时，LLM 在对话中直接写 markdown/HTML，时间由用户自己填。
