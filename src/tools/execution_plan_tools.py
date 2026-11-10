"""阶段 9 执行方案校准 MCP 工具。"""

from __future__ import annotations

from ..core.stages import execution_plan as _stage
from ..mcp_app import mcp
from .errors import error_response
from .profile import load_profile
from .state_gate import require_state
from .tool_helpers import _json


@mcp.tool()
def plan_execution_alignment(requirement_profile_id: str = "") -> str:
    """准备执行方案校准上下文（阶段 9 第一步，不写档案）。

    何时调用：阶段 8 的 RequirementProfile 已保存，用户准备把基线路线图
    升级为执行版时。

    前置条件：档案已有基线路线图（profile.plan），且存在 RequirementProfile。

    Args:
        requirement_profile_id: RequirementProfile artifact id；
            为空时取当前档案最新的 RequirementProfile。

    返回 JSON（字符串）：
        - methodology: 校准方法论（原则、步骤、output_schema）
        - requirement: 需求摘要（高频要求、公司特定要求、硬门槛、interpretation）
        - baseline_plan: 当前基线路线图
        - completed_evidence: 已完成/已跳过任务（代码提取，含 how_to/done_criteria）
        - capability_evidence: 档案中沉淀的能力证据（可选）
        - alignment_prompt: 给 LLM 的输出模板与规则（每条 change 必须带 evidence_ids）

    下一步：LLM 设计好 strategy_summary / roadmap / changes / diff_summary 后，
    调用 save_execution_alignment 预览；用户确认后再传 confirmed=true 应用。
    """
    profile = load_profile()
    gate = require_state(profile, "plan_execution_alignment")
    if isinstance(gate, str):
        return gate

    try:
        result = _stage.plan_execution_alignment(requirement_profile_id)
    except _stage.ExecutionPlanError as exc:
        return error_response(exc.code, exc.message, exc.details)
    return _json(result)


@mcp.tool()
def save_execution_alignment(alignment_json: str, confirmed: bool = False) -> str:
    """预览或应用执行方案校准（用户确认是硬门禁）。

    何时调用：完成 plan_execution_alignment 后，LLM 设计了执行版路线图与变更清单。

    校验纪律（代码执行，LLM 不可绕过）：
    - requirement_profile_id 必须存在，且与当前档案需求链路一致；
    - roadmap.phases 非空，每个 phase 有 name/goal，milestones/tasks 结构合法；
    - 每条 change 的 type 合法且 evidence_ids 非空——没有证据的变更不允许落库；
    - diff_summary 必填。

    Args:
        alignment_json: 校准方案 JSON 字符串，Schema：
            {
                "requirement_profile_id": "rp_...",
                "strategy_summary": "执行版整体策略",
                "roadmap": {
                    "strategy_summary": "与顶层一致",
                    "phases": [
                        {
                            "type": "learn/project/intern/research",
                            "name": "阶段名",
                            "goal": "阶段目标",
                            "kpi": {"metric": "", "target": "", "evidence": ""},
                            "milestones": [
                                {
                                    "name": "里程碑",
                                    "done_criteria": "",
                                    "tasks": [{"name": "", "description": "", "priority": "high"}]
                                }
                            ]
                        }
                    ]
                },
                "changes": [
                    {
                        "type": "add_task/modify_task/remove_task/reorder_tasks/"
                                "modify_phase/add_phase/remove_phase/reorder_phases",
                        "phase_id": "",
                        "task_id": "",
                        "details": {"name": ""},
                        "reason": "",
                        "evidence_ids": ["JD001"]
                    }
                ],
                "diff_summary": "本次校准的差异摘要"
            }
        confirmed: 用户是否已确认应用。false 只保存预览 artifact，返回 diff 与
            确认提示，不修改档案；true 才替换 profile.plan、维护 plan_history /
            adjustments / core_state 并刷新职业地图。

    返回 JSON（字符串）：
        - confirmed=false: status=needs_confirmation，含 baseline/proposed 概览、
          changes、保留/移除任务清单与确认提示；
        - confirmed=true: status=ok，含应用摘要、execution_plan_id、map_path、
          next_steps（get_next_tasks / generate_tasks）。
    """
    profile = load_profile()
    gate = require_state(profile, "save_execution_alignment")
    if isinstance(gate, str):
        return gate

    try:
        result = _stage.save_execution_alignment(alignment_json, confirmed=confirmed)
    except _stage.ExecutionPlanError as exc:
        return error_response(exc.code, exc.message, exc.details)
    return _json(result)
