"""Core v2 阶段 8 MCP 工具：企业需求分析。

analyze_company_requirements 返回确定性统计与受约束的分析提示；
save_requirement_profile 只接收 LLM 的 interpretation，数字由代码重新计算后落库。
"""

from __future__ import annotations

from ..core.artifacts.models import EvidenceRun, RequirementProfile
from ..core.artifacts.store import ArtifactStore
from ..core.orchestrator import state_machine
from ..core.stages import requirements
from ..core.stages.base import StageContext
from ..mcp_app import mcp
from .errors import InvalidJsonError, error_response
from .profile import get_active_profile_name, load_profile
from .state_gate import require_state
from .tool_helpers import _json, _parse_json_param

_ALLOWED_TOP_KEYS = {"requirement_profile_id", "interpretation"}


@mcp.tool()
def analyze_company_requirements(evidence_run_id: str = "") -> str:
    """企业需求分析：统计 JD 与面经的确定性数据，并返回 LLM 解读提示。

    何时调用：collect_company_evidence 之后、plan_execution_alignment 之前。
    evidence_run_id 为空时使用当前档案最新的 EvidenceRun。

    产出：RequirementProfile 草稿（id 前缀 rp_）落库到 artifact store，
    并更新档案 core_state。数字、公司覆盖、Wilson 区间与硬门槛均由代码计算；
    LLM 只能按 analysis_prompt 填写 interpretation。

    Args:
        evidence_run_id: 目标 EvidenceRun id；空串取当前档案最新一次采集。

    Returns:
        统计摘要 + analysis_prompt + 下一步（save_requirement_profile）。
    """
    profile = load_profile()
    gate = require_state(profile, "analyze_company_requirements")
    if isinstance(gate, str):
        return gate

    profile_name = get_active_profile_name()
    store = ArtifactStore()
    result = requirements.run(
        StageContext(profile_name=profile_name, store=store),
        {"evidence_run_id": evidence_run_id},
    )
    if result.status == "failed":
        return error_response("EVIDENCE_RUN_NOT_FOUND", result.message)

    data = store.load(result.artifact_id)
    if data is None:
        return error_response("ANALYSIS_FAILED", "需求画像已生成但无法读取，请重试")
    artifact = RequirementProfile.model_validate(data)

    payload = requirements.summary_dict(artifact)
    payload["status"] = "ok"
    payload["analysis_prompt"] = requirements.build_analysis_prompt(artifact)
    payload["next_step"] = (
        "调用 save_requirement_profile，传 requirement_profile_id 与 interpretation"
        "（只写 summary/priorities/company_notes/risks/notes）"
    )
    return _json(payload)


@mcp.tool()
def save_requirement_profile(analysis_json: str) -> str:
    """保存企业需求的定性解读，数字由代码复核。

    何时调用：analyze_company_requirements 返回 analysis_prompt 之后。

    Args:
        analysis_json: JSON 字符串，必须包含 requirement_profile_id 与 interpretation。
            interpretation 只允许 summary、priorities、company_notes、risks、notes；
            任何数字/列表字段（high_frequency、gaps 等）都会被拒绝。

    Returns:
        保存摘要 + 下一步（plan_execution_alignment）。
    """
    profile = load_profile()
    gate = require_state(profile, "save_requirement_profile")
    if isinstance(gate, str):
        return gate

    try:
        data = _parse_json_param(analysis_json, "需求分析")
    except InvalidJsonError as exc:
        return error_response(exc.code, exc.message, exc.details)

    extra_top = sorted(set(data) - _ALLOWED_TOP_KEYS)
    if extra_top:
        return error_response(
            "INVALID_PARAM",
            "只允许 requirement_profile_id 与 interpretation 两个顶层字段；"
            f"数字与列表由代码生成，不能覆盖。拒绝字段：{extra_top}",
            {"received": extra_top, "allowed": sorted(_ALLOWED_TOP_KEYS)},
        )

    profile_id = str(data.get("requirement_profile_id") or "").strip()
    if not profile_id:
        return error_response(
            "INVALID_PARAM",
            "缺少 requirement_profile_id——先调用 analyze_company_requirements 获取草稿 id",
            {"allowed": ["requirement_profile_id"]},
        )

    interpretation = data.get("interpretation")
    if not isinstance(interpretation, dict):
        return error_response(
            "INVALID_PARAM",
            "interpretation 必须是 JSON 对象，只允许 "
            f"{list(requirements.INTERPRETATION_KEYS)}",
            {"received": type(interpretation).__name__},
        )
    invalid_keys = sorted(set(interpretation) - set(requirements.INTERPRETATION_KEYS))
    if invalid_keys:
        return error_response(
            "INVALID_INTERPRETATION",
            "interpretation 只允许 "
            f"{list(requirements.INTERPRETATION_KEYS)}；拒绝字段：{invalid_keys}。"
            "数字、列表与 evidence_ids 由代码生成，LLM 不得改写。",
            {"received": invalid_keys, "allowed": list(requirements.INTERPRETATION_KEYS)},
        )

    profile_name = get_active_profile_name()
    store = ArtifactStore()
    draft_data = store.load(profile_id)
    if not isinstance(draft_data, dict):
        return error_response(
            "REQUIREMENT_PROFILE_NOT_FOUND",
            f"需求画像草稿「{profile_id}」不存在——先调用 analyze_company_requirements",
            {"requirement_profile_id": profile_id},
        )
    meta = draft_data.get("meta")
    if not isinstance(meta, dict) or meta.get("stage") != requirements.STAGE_ID:
        return error_response(
            "INVALID_ARTIFACT",
            f"artifact「{profile_id}」不是 RequirementProfile 草稿",
            {"requirement_profile_id": profile_id},
        )
    if str(meta.get("profile_name") or "") != profile_name:
        return error_response(
            "INVALID_ARTIFACT",
            f"需求画像草稿属于档案「{meta.get('profile_name')}」，当前档案是「{profile_name}」",
            {"requirement_profile_id": profile_id},
        )

    try:
        draft = RequirementProfile.model_validate(draft_data)
    except Exception as exc:  # noqa: BLE001 —— 损坏数据要变成可读错误
        return error_response(
            "INVALID_ARTIFACT",
            f"需求画像草稿数据损坏：{exc}",
            {"requirement_profile_id": profile_id},
        )

    merged_interpretation = {**draft.interpretation, **interpretation}
    final = draft.model_copy(deep=True)
    final.interpretation = merged_interpretation

    evidence_run_id = final.evidence_run_id.strip()
    if not evidence_run_id:
        return error_response(
            "EVIDENCE_RUN_NOT_FOUND",
            "需求画像草稿没有 evidence_run_id，无法复算统计，拒绝落库。",
            {"requirement_profile_id": profile_id},
        )
    evidence_data = store.load(evidence_run_id)
    if not isinstance(evidence_data, dict):
        return error_response(
            "EVIDENCE_RUN_NOT_FOUND",
            f"EvidenceRun「{evidence_run_id}」不存在，拒绝沿用草稿统计落库。",
            {"requirement_profile_id": profile_id, "evidence_run_id": evidence_run_id},
        )
    evidence_meta = evidence_data.get("meta")
    if not isinstance(evidence_meta, dict) or evidence_meta.get(
        "stage"
    ) != state_machine.STAGE_EVIDENCE:
        return error_response(
            "EVIDENCE_RUN_NOT_FOUND",
            f"artifact「{evidence_run_id}」不是 EvidenceRun，拒绝落库。",
            {"requirement_profile_id": profile_id, "evidence_run_id": evidence_run_id},
        )
    if str(evidence_meta.get("profile_name") or "") != profile_name:
        return error_response(
            "EVIDENCE_RUN_NOT_FOUND",
            f"EvidenceRun「{evidence_run_id}」不属于当前档案，拒绝落库。",
            {"requirement_profile_id": profile_id, "evidence_run_id": evidence_run_id},
        )
    try:
        evidence = EvidenceRun.model_validate(evidence_data)
        stats = requirements.compute_statistics(evidence, profile=profile)
    except Exception as exc:  # noqa: BLE001 —— 证据损坏必须拒绝，不沿用草稿数字
        return error_response(
            "EVIDENCE_RUN_CORRUPT",
            f"EvidenceRun「{evidence_run_id}」数据损坏，无法复算统计，拒绝落库：{exc}",
            {"requirement_profile_id": profile_id, "evidence_run_id": evidence_run_id},
        )

    # 数字一律由代码从 EvidenceRun 重算，忽略草稿里可能被改动的统计。
    final = RequirementProfile(
        meta=final.meta,
        evidence_run_id=evidence_run_id,
        interpretation=merged_interpretation,
        **stats,
    )
    # 标记为已保存/已解读：progress 只放行草稿之外的需求画像进入阶段 9。
    final.meta.validation = {
        **(final.meta.validation or {}),
        "status": "saved",
        "interpreted": True,
    }

    issues = requirements.validate(final)
    if issues:
        return error_response(
            "INVALID_ARTIFACT",
            "需求画像校验失败，未保存：" + "；".join(issues),
            {"requirement_profile_id": profile_id, "issues": issues},
        )

    store.save(final)
    stored = store.load(final.meta.id) or {}
    stored_meta = stored.get("meta") if isinstance(stored.get("meta"), dict) else {}
    version = int(stored_meta.get("version") or final.meta.version or 1)
    requirements.update_core_state(profile_name, final.meta.id)

    payload = requirements.summary_dict(final)
    payload["status"] = "ok"
    payload["revalidated"] = True
    payload["version"] = version
    payload["interpretation_keys"] = sorted(merged_interpretation)
    payload["next_step"] = "调用 plan_execution_alignment 进入阶段 9（执行方案校准）"
    return _json(payload)


__all__ = ["analyze_company_requirements", "save_requirement_profile"]
