# 计划失配检测（check_plan_fit）

目标：用确定性事实判断「旧计划是否还适合新证据」，把是否需要调整的决定交回用户。

## 何时调用

- 证据池刷新后：`check_plan_fit(trigger="evidence_refresh")`
- 完成一个里程碑后：`check_plan_fit(trigger="milestone")`
- 周检视时：`check_plan_fit(trigger="weekly_review")`
- 用户主动问「计划还合适吗」：`check_plan_fit(trigger="manual")`

## 规则

1. 先调用 `check_plan_fit`，再做任何计划相关表述；不要凭记忆判断计划是否过期。
2. 返回 `status=major_drift` 时，必须把 `question_for_user` 的意思转问用户，
   等用户表态；不要替用户决定，也不要直接改计划。
3. 用户同意后，才按返回的 `next_tool` 继续：
   - `collect_company_evidence`：重新采集岗位与面经证据；
   - `analyze_company_requirements`：重做企业需求分析；
   - `plan_execution_alignment`：重新校准执行方案；
   - `analyze_gaps`：目标变化后重跑差距分析；
   - `get_weekly_review`：先做周检视复盘。
4. 不要自动改档案、不要自动刷新证据、不要跳过用户确认。
5. `status=aligned` 时不要制造问题；只说明「当前证据与计划没有发现不一致」。
6. `status=incomplete_chain` 时只说明链路尚未建立，不把它说成计划失配。

## 输出纪律

- 只陈述工具返回的事实与证据（signal code / severity / evidence_ids），不补充推测。
- 置信度为 low 或出现 `insufficient_sample` 时，明确说样本不足，不下全局结论。
- `stale_evidence`、`funnel_signal` 只提示可能需要复盘/刷新，不直接等同于计划错误。
- 用「可能需要校准 / 建议先看事实」这类中性表述，不制造焦虑、不催不赶。
