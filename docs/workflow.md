# 工作流详解

> 12 个阶段的目标、前置条件、流程与产物。工具清单见 [tools.md](tools.md)。
> 核心理念：**顺序归产品，时间归用户**——不为任务设定时限。

## 工作流总览

```text
1 职业档案构建 → 2 目标岗位定位 → 3 市场基线调研 → 4 能力差距诊断
→ 5 培养方案规划 → 6 目标企业筛选 → 7 岗位与面经采集 → 8 企业需求分析
→ 9 执行方案校准 → 10 任务执行与打卡 → 11 求职投递管理
→ 12 周期复盘与计划调整 → 循环
```

每个阶段只产出一个 artifact，下一阶段只读这个 artifact，不依赖会话记忆。
阶段 11/12 是可选/周期性阶段，不阻塞阶段 10 的执行。
阶段 6-9 是执行前必做的企业适配链路，完成后才进入阶段 10。

**上游引用契约（阶段 2-10）**：下游 artifact 必须通过 body 字段或
`meta.inputs` 引用上游 id，空引用视为不满足；下游 artifact 存在也不能让缺失的
上游阶段被跳过。artifact 的 `meta.stage` 取值包括
`profile / target / market_baseline / gap / baseline_plan / company_pool /
evidence / requirement / execution_plan / execution / applications / review`；
`core_state.stage` 与 artifact 阶段基本同源，但阶段 10 例外：artifact 用
`execution`，执行态 `core_state.stage` 写 `executing`（见 save_execution_alignment）。

---

## 阶段 1：职业档案构建

**目标**：建立可核验的档案，摸清真实水平（简历有美化成分，包括 AI 写的代码——作者身份要说清）。

**流程**：

```text
1. start_session()
2. parse_resume(file_path)   # 可选：解析简历素材
3. intake(who)               # 姓名、教育、当前状态、毕业年份
4. intake(have)              # 技能、经历、资源；每条技能带 evidence + verified + authorship
                             # + control_level（0-10）；整份自评写 have.self_assessment
5. finalize_profile()
```

> 摸排硬门禁：技能无用户确认证据，或缺 authorship/control_level/self_assessment 时，
> finalize 与 analyze_gaps 都会拒绝放行；authorship/control_level 必须来自用户本人回答，
> AI 不得代填。唯一跳过方式是用户明确要求时 `finalize_profile(skip_probing=True)`。

**产物**：`ProfileSnapshot`（`pf_`）+ `profile.summary`。
`ProfileSnapshot` 模型本身不带 `meta`，由 `core.sync` 包装成带 `ArtifactMeta`
的持久化 artifact（`meta.stage=profile`）。

---

## 阶段 2：目标岗位定位

**目标**：确定方向、城市、最终档位与过渡档位，并得到用户明确确认。

**流程**：

```text
1. 有明确目标：复述方向/城市/届别 → intake(want, user_confirmed=true)
2. 方向模糊：explore_goals() → 对话选定 → intake(want, user_confirmed=true)
3. 有 JD 文件：import_jd_file() / import_jd()
```

**产物**：`TargetSpec`（`ts_`）+ `profile.want`。
`TargetSpec` 同样由 `core.sync` 包装持久化，`meta.inputs.profile_id` 必须指向
当前档案的 `ProfileSnapshot`。

**关键规则**：模型从简历推断的目标只能作为候选，未确认时 GUIDE 停在 goal 状态；
目标变更后旧分析和计划可能过期，后续用 `check_plan_fit` 检测。

---

## 阶段 3：市场基线调研

**目标**：抓取真实市场事实，生成可查证的调研报告——后续差距分析的地基。

**流程**：

```text
1. research_market()                              # 方法论与 4 步模板
2. 向用户播报调研菜单（抓哪家、耗时、报告落在哪），宣告即执行
3. 名单含 BOSS 时先问一次是否抓取；同意后先 boss_login(status)，未就绪直接 login
4. 登录成功后 gather_research_data(jd_specs, case_query, boss_confirmed)
   - 目标公司 1 家 + 同方向对照 2-4 家
   - 逐条补抓岗位详情；无详情岗位剔除并计入缺口
   - 单源 25 秒 / 总预算 50 秒；超过 2 个源建议拆批；失败不拖垮整批，已完成来源写断点缓存
5. 报告三件套自动落盘（代码渲染，不经 LLM）
6. 按需读取全文：read_research_details(ids=..., kind="jd"/"case")
```

**产物**：`MarketBaseline`（`mb_`）+ `~/CareerKit/<档案>/调研报告/<日期_方向>.{md,html,json}`。

**关键规则**：
- 报告 100% 代码渲染自抓取数据，每条带来源链接、平台、抓取时间。
- 任一源失败不中断，失败原因进来源状态面板；未获取内容写「未获取」，不编造。
- 全部失败时返回 `MISSING_DATA`，引导 `import_jd` / `import_jd_file`。
- BOSS 登录缺失时直接调用 `boss_login(action="login")`；登录页为
  `https://www.zhipin.com/web/user/?ka=header-login`；扫码成功后窗口常驻复用，不自动关闭；
  需要关闭时调用 `boss_login(action="close")`。
  研究阶段 BOSS 为 list-only（公司/地点/明文薪资/技能），详情在交互式 `fetch_jd_detail` 中补抓。

---

## 阶段 4：能力差距诊断

**目标**：基于真实市场数据找出差距，给出起点档位与优先补强项。

**流程**：

```text
1. 优先引用 profile.research：read_research_details() 取花名册与聚合摘要
2. 必要时补数据：fetch_company_jobs / fetch_jd_detail / search_cases / search_knowledge
3. analyze_gaps() → 按 4 步 step_template 执行
4. save_gap_analysis(gap_json)
```

**产物**：`GapReport`（`gr_`）+ `profile.gap`（`match_score`、`skill_gaps`、
`priority_actions`、`resume_red_flags`、`start_level`）。

**关键规则**：
- 分析必须基于真实数据；无数据时引导用户导入 JD，绝不编造。
- `skill_gaps` 非空时每项必须带 `skill` 与 `source`，缺失返回 `INVALID_PARAM` 且不写档案；
  空 `skill_gaps` 允许保存但会给建议；`resume_red_flags` 带 `signal` / `risk` / `evidence_fix`。
- 过程透明：每步产出用户看得见的中间结果，落盘前用户确认。
- 换了目标 JD 后差距分析标记过期，必须先重新 `analyze_gaps`。

---

## 阶段 5：培养方案规划

**目标**：基于差距生成分阶段路线图，只定顺序与完成标准，得到「方向基线」。

**流程**：

```text
1. generate_roadmap()
2. save_roadmap(roadmap_json)                         # 先保存结构
3. career-roadmap-auditor 审计 → save_roadmap_audit() # 第二意见，不阻断
4. 按需修正后再次 save_roadmap
```

**产物**：`BaselinePlan`（`bp_`）+ `profile.plan` + 可交互职业地图。

**关键规则**：
- `save_roadmap` 只做结构校验；质量项以 `advisories` 返回并持久化。
- 层级是命中率参考，不是准入许可；跨级不禁止，建议说明证据。
- 审计是第二意见：FAIL 只用于硬矛盾，最多 3 条 must_fix。
- JD 细节必须有真实数据；没有就留空并标 `jd_status=pending_user_import`。
- 产品不排期：任务名不带时间节奏词。

---

## 阶段 6：目标企业筛选

**目标**：把档位落到具体企业，得到用户确认的目标企业池。

**流程**：

```text
1. select_target_companies(target_tiers, bridge_tiers, city, role, industry, confirmed=false)
2. 向用户展示推荐名单（可抓 / 需手动投递）
3. 用户增删后 confirmed=true 重新调用
```

**产物**：`CompanyPool`（`cp_`）+ `core_state.company_pool_id`。

**关键规则**：
- 未接入抓取的企业保留在名单中并标「需手动投递」，不编造岗位。
- 企业池未确认时不得进入采集。
- 支持 include/exclude；同一企业同时出现时 include 优先。

---

## 阶段 7：岗位与面经采集

**目标**：批量采集目标企业的真实 JD 与面经，形成可追溯的证据池。

**流程**：

```text
collect_company_evidence(
  company_pool_id,
  per_company_limit=5,
  max_companies=15,
  max_jd=50,
  max_interviews=30,
  refresh=false,
  include_boss=false,       # 可选：补充 BOSS 薪资与广度
  boss_confirmed=false      # 含 BOSS 时先问用户，同意后传 true
)
```

**产物**：`EvidenceRun`（`ev_`）+ `~/CareerKit/<档案>/证据池/<日期_方向>.{md,html,json}`。

**关键规则**：
- 只抓已确认且可抓的企业；城市是硬筛选。
- 目标城市非空时，`location` 为空的岗位按硬筛剔除，同时计入 `unknown_city`
  与 `dropped_city`，并写入数据缺口（空 location 不能静默放行）。
- 官方源 JD 必须抓到详情；无详情剔除并计入 `dropped_no_detail`。
- BOSS 的 `detail_status=list_only` 行尊重来源声明：不补详情、不剔除，
  保留薪资/公司/地点/技能等列表字段，并计入 list-only 缺口；
  需要全文时由用户显式调用 `fetch_jd_detail`。
- 单源失败不拖垮整批，失败原因进 `source_status` 与 `gaps`。
- 复用 `profile.research` 中 7 天内的样本，按 URL/公司+标题去重。
- 置信度只按样本量计算（与 RequirementProfile 同口径）：
  JD <15 low / 15-29 medium / >=30 high；
  面经 <10 low / 10-19 medium / >=20 high。
- 面经与 JD 分开统计；面经无法对应企业时保留为通用面经。

---

## 阶段 8：企业需求分析

**目标**：把证据池变成结构化需求画像，而不是让 LLM 凭印象总结。

**流程**：

```text
1. analyze_company_requirements(evidence_run_id)
2. 按 analysis_prompt 填 interpretation
3. save_requirement_profile(analysis_json)
```

**产物**：`RequirementProfile`（`rp_`）。

**关键规则**：
- 频率、公司覆盖、Wilson 95% 区间、逐条硬门槛全部由代码计算。
- 高频共性：`jd_frequency >= 0.5` 且 `company_count >= 2`；样本不足时降级为观察。
- 不再使用「必备项」：区分高频共性要求、单 JD 硬门槛、面经高频考点、
  公司差异化要求、加分项。
- LLM 只能写 `summary / priorities / company_notes / risks / notes`；
  数字、列表与 evidence_ids 由代码复核，LLM 不得改写。

---

## 阶段 9：执行方案校准

**目标**：用需求画像把「方向基线」升级为「执行版」，从档位落到具体企业。

**流程**：

```text
1. plan_execution_alignment(requirement_profile_id)
2. 按 alignment_prompt 设计执行版路线图与 changes
3. save_execution_alignment(alignment_json, confirmed=false)  # 预览 diff
4. save_execution_alignment(alignment_json, confirmed=true)   # 应用
5. detail_current_phase() → generate_tasks()
```

**产物**：`ExecutionPlan`（`ep_`）+ 替换后的 `profile.plan` + `plan_history` + `adjustments`。

**关键规则**：
- 每条 change 必须带 `evidence_ids`；没有证据的变更不允许落库。
- 已完成/已跳过任务是历史，不能删除；旧 pending/in_progress 不迁移。
- 用户确认是硬门禁：未确认只返回 diff 预览，不改档案。
- 应用后重新生成当前阶段任务；任务 ID 按「阶段+里程碑+任务名」复用。

---

## 阶段 10：任务执行与打卡

**目标**：把执行版路线图转成可执行任务，关卡式推进。

**流程**：

```text
1. detail_current_phase()              # 建议先细化当前阶段
2. save_current_detail(detail_json)    # how_to / resources / done_criteria + 打卡点
3. generate_tasks()                    # 只生成当前阶段 + 刷新职业地图
4. get_next_tasks()
5. checkin_task(task_id, status, notes, amount)
```

**产物**：`ExecutionState`（`es_`）+ `profile.tasks` + `profile.have.capability_evidence`。

**关键规则**：
- `checkin_mode`：`once` / `daily`（amount 累加天数）/ `percent`（amount 累加比例）。
- `ExecutionState` 只在存在 applied `ExecutionPlan` 且 `execution_plan_id` 非空时写入。
- 只有匹配当前 applied plan 的 `ExecutionState` 才进入 `get_next_tasks`；
  旧计划留下的任务需先 `generate_tasks` 重新生成。
- 完成得轻松时可在对话中建议加深，但不自动繁殖任务。
- 产品不为任务设定时限。

---

## 阶段 11：求职投递管理

**目标**：记录投递、面试、offer 与漏斗转化；可选阶段，不阻塞任务执行。

**流程**：

```text
build_application_list(city, role, top=30, min_score=0)  # 从证据池批量生成投递清单
record_application(company, role, status, channel, source, notes)
delete_application(application_id)   # 仅录错/重复时
```

**产物**：`ApplicationState`（`as_`）+ `profile.applications` + 漏斗统计 +
`candidates`（由 `build_application_list` 生成并保存的投递清单）。

**关键规则**：
- 只记录用户口述的真实事实，不编造、不代用户估计状态。
- 投递清单城市是硬筛：目标城市非空时 `location` 为空的候选剔除，并计入未知城市缺口；
  目标城市为空时保留所有岗位。
- 同公司+同岗位的活跃记录不重复新建；返回现有 `application_id`。
- 转化率按事件历史统计：面试后被拒仍计入面试数；样本 <5 时降级为参考。
- 进面试/拿 offer 是重大事件，按返回值提示触发 `trigger_insight(event)`。

---

## 阶段 12：周期复盘与计划调整

**目标**：用事实复盘打卡/阶段/漏斗；数据或目标变化时检测计划是否失配。

**流程**：

```text
1. get_weekly_review(days=7 或 30)
2. check_plan_fit(trigger="weekly_review" | "evidence_refresh" | "milestone" | "manual")
3. 有 major_drift：把 question_for_user 转问用户；用户同意后再 refresh / 重新校准
4. trigger_insight(trigger_type="stage_audit" | "event") → apply_insight()
```

**产物**：`ReviewReport`（`rr_`）+ `profile.adjustments` + `profile.audited_phases`。

**关键规则**：
- 周检视只陈述事实（如「距上次打卡 N 天」），不判定超期、不催促。
- `check_plan_fit` 只检测、不改计划；signals 带 code / severity / message / evidence_ids。
- 证据超过 7 天提示刷新；高频要求未覆盖、执行版过期、目标变化会给出不同严重度。
- 漏斗样本 <5 时不下转化率结论。

---

## 档案管理

| 工具 | 作用 |
|------|------|
| `list_profiles` | 列出所有档案 |
| `switch_profile` | 切换当前档案 |
| `delete_profile` | 回收站式删除（需 `confirm="true"`，可恢复） |
| `list_trash` | 查看回收站 |
| `restore_profile` | 从回收站恢复 |

---

## 产出与状态

用户资产统一落 `~/CareerKit/`（`CAREER_KIT_ASSETS_DIR` 可覆盖）：
`index.html` 是总入口，调研报告/证据池按 `<日期_方向>` 留档，路线图与仪表盘用固定文件名。

资产中心按「规划链路」展示（每一步只引用真实存在的文件，缺失时给出下一步）：
基线方案 → 目标企业 → 证据池 → 企业需求 → 执行版 → 投递清单。
其中基线方案与执行版共用 `路线图/路线图.html`（执行版会覆盖并在地图顶部标注），
目标企业与需求画像来自档案 artifact 与证据池报告，不单独生成空文件；
投递清单落 `投递清单/`。

| 工具 | 产出 |
|------|------|
| `get_progress` | 整体进度（含求职漏斗与投递清单） |
| `get_workflow_status` | 12 阶段当前位置 + 下一步 + 目标变更检测 + 周检视/计划失配提示 |
| `get_weekly_review` | 周检视 Markdown（打卡/阶段/漏斗 + 规则化建议 + 计划失配） |
| `check_plan_fit` | 计划失配信号 + 给用户的询问话术（只读） |
| `export_dashboard("progress")` | 进度仪表盘 |
| `export_dashboard("roadmap")` | 可交互职业地图 |

日程表不存储：用户需要时，LLM 在对话中直接写 markdown/HTML，时间由用户自己填。
