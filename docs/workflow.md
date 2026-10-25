# 工作流详解

> 各阶段的目标、前置条件、流程与输出。工具清单见 [tools.md](tools.md)。

核心理念：**顺序归产品，时间归用户**——不为任务设定时限。

## 工作流总览

```
建档 → 分析 → 规划 → 任务执行 → 打卡 → 阶段审计/事件洞察 → 循环
```

---

## 阶段 1：建档

**目标**：建立档案，摸清真实水平（简历有美化成分）。

**前置条件**：无。

**流程**：

```
1. start_session()
2. parse_resume(file_path)   # 可选：解析简历素材，技能仍需逐项确认
3. intake(who)      # 姓名、教育、当前状态；缺毕业年份时补 graduation_year
4. intake(have)     # 技能、经历、资源；关键技能追问 evidence + verified
5. 确定目标：
   - 有明确目标 → intake(want)
   - 方向模糊 → explore_goals() → 对话选定 → intake(want)
   - 有 JD 文件 → import_jd_file() / import_jd()
6. finalize_profile()
```

**输出**：

- `profile.summary`：档案摘要
- `profile.section_updated_at`：目标变更检测依据

**关键规则**：

- 技能必须经过用户确认，简历原文不能直接当证据
- 有技能但无确认证据时，`finalize_profile` 会拒绝放行；仅用户明确要求时可
  `skip_probing=True` 并留痕

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
2. 每个 `skill_gaps` 条目必须标注 `source`
3. 每条 `resume_red_flags` 必须带 `signal` / `risk` / `evidence_fix`
4. 薪资行情从岗位搜索结果的 `salary` 字段汇总

---

## 阶段 3：规划

**目标**：基于差距生成分阶段路线图，只定顺序与完成标准。

**前置条件**：`profile.gap` 已生成。

**流程**：

```
1. generate_roadmap()
2. save_roadmap(roadmap_json)
```

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

**关键规则**：

- `checkin_mode`：`once`（默认）/ `daily`（`amount` 累加天数）/
  `percent`（`amount` 累加完成比例）
- 完成得轻松时可在对话中建议加深，但不自动繁殖任务

---

## 阶段 5：洞察调整

**目标**：阶段完成后审计，用户报告事件时重估计划。

**前置条件**：`profile.tasks` 已生成。

**流程**：

```
1. trigger_insight(trigger_type="stage_audit" | "event", event_description)
2. apply_insight(insight_json)
```

**输出**：

- `profile.adjustments`：调整记录
- `profile.audited_phases`：已审计阶段（每阶段只审计一次）

| 类型 | 触发时机 | 示例 |
|------|----------|------|
| `stage_audit` | 完成阶段后 | 完成实习后评估含金量 |
| `event` | 用户报告事件 | 拿到大厂面试 |

> 「主动检查 / 超期压缩」已移除——产品不为任务设定时限。

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
| `get_progress` | 整体进度 |
| `get_workflow_status` | 当前阶段 + 下一步 + 目标变更检测 |
| `export_dashboard("progress")` | 自包含进度仪表盘 |
| `export_dashboard("roadmap")` | 可交互职业地图 |

日程表不存储：用户需要时，LLM 在对话中直接写 markdown/HTML，时间由用户自己填。
