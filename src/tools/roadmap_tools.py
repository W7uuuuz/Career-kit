"""路线图生成、质量建议与计划导入 MCP 工具。"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from ..mcp_app import mcp
from .dashboard import render_roadmap_map as _render_roadmap_map, write_html as _write_html
from .errors import InvalidJsonError, error_response
from .methodology import build_methodology_context
from .profile import load_profile, save_plan_snapshot, save_profile
from .roadmap import format_roadmap, parse_roadmap
from .tool_helpers import _json, _parse_json_param


@mcp.tool()
def generate_roadmap() -> str:
    """基于差距分析生成分阶段职业路线图。

    返回方法论上下文。LLM 按照方法论指引，结合差距分析结果，
    设计分阶段路线图，然后调用 save_roadmap(roadmap_json) 保存。

    前置条件：差距分析已完成（save_gap_analysis 已调用）。
    后续步骤：LLM 生成路线图后调用 save_roadmap，然后调用 generate_tasks。
    """
    profile = load_profile()

    if not profile.gap:
        return error_response(
            "MISSING_DATA",
            "请先调用 analyze_gaps 完成差距分析，再生成路线图。",
            {"missing": "gap"},
        )

    ctx = build_methodology_context("roadmap", profile, compact=True)

    return _json({
        "next_steps": ["save_roadmap", "generate_tasks"],
        "methodology": ctx["methodology"],
        "profile": ctx["profile"],
        "step_template": [
            {
                "step": 1,
                "name": "起点判定",
                "action": "用 roadmap.yaml 的 start_level_rubric 打分表逐维度评分（学历/实习/协作/技能/项目），"
                          "加权求总分映射档位（大厂/中厂/小厂/暂不可入），输出各维度得分 + 判定依据",
                "output": {"start_level": "档位", "dimension_scores": {"education": 0, "internship": 0, "collaboration": 0, "skill_depth": 0, "project_complexity": 0}, "rationale": "为什么是这个档位"},
                "checkpoint": True,
                "checkpoint_note": "把起点层级展示给用户确认后再进下一步",
            },
            {
                "step": 2,
                "name": "目标拆解",
                "action": "从 want/target_jd 提取目标角色与目标公司；层级只作命中率参考，"
                          "重点判断目标岗位需要哪些证据（项目/实习/开源/内推），当前缺什么",
                "output": {"target_role": "", "target_level": "参考档位（可选）", "evidence_needed": [], "evidence_have": []},
                "checkpoint": False,
            },
            {
                "step": 3,
                "name": "阶段序列设计",
                "action": "按「补齐证据 → 提高命中率」设计阶段序列（learn/project/intern/...）；"
                          "层级不是准入许可，跨级不禁止，但请在阶段理由中说明依据（作品集/内推/前序交付）；"
                          "每阶段标注类型、目标、需要补齐的证据、投递通道",
                "output": {"phases_sequence": [{"type": "", "name": "", "target_level": "", "evidence_gate": [], "access_path": "", "transition_reason": ""}]},
                "checkpoint": True,
                "checkpoint_note": "把阶段序列展示给用户确认后再逐阶段细化",
            },
            {
                "step": 4,
                "name": "逐阶段深入细化",
                "action": "对每个阶段深入展开：KPI（尽量可验证）、里程碑（带完成标准）、"
                          "任务（一次坐下可完成粒度）、jd 三件套（company/rationale 常识可写，jd/jd_status 真实数据才填——"
                          "优先引用档案 research 里的调研 JD 样本与来源，不再重复抓取）",
                "output": "完整 roadmap JSON（strategy_summary + phases，符合 roadmap.yaml output_schema）",
                "checkpoint": False,
            },
            {
                "step": 5,
                "name": "保存雏形 + 审计（第二意见）",
                "action": "先调用 save_roadmap(roadmap_json) 保存当前雏形（结构校验通过即可，"
                          "质量项只作建议）；再调用 career-roadmap-auditor 按 roadmap.yaml "
                          "audit_checklist 检查，输出 PASS / PASS_WITH_NOTES / FAIL，"
                          "FAIL 只用于硬矛盾、最多 3 条 must_fix；随后调用 save_roadmap_audit 落库。"
                          "审计不阻断定稿，是否修改由 LLM 与用户决定，不做无界重审",
                "output": {"verdict": "PASS/PASS_WITH_NOTES/FAIL", "issues": [{"checklist_id": "", "problem": "", "fix": ""}], "notes": []},
                "checkpoint": False,
            },
            {
                "step": 6,
                "name": "定稿交付",
                "action": "按需采纳审计建议与质量提示后，再次调用 save_roadmap(roadmap_json) 完成定稿；"
                          "一次性展示全流程雏形（所有阶段/目标/KPI/里程碑/顺序理由），"
                          "保存后如实复述质量建议与审计未解决项，由用户决定是否继续调整",
                "output": "save_roadmap(roadmap_json)",
                "checkpoint": True,
                "checkpoint_note": "用户确认整份路线图后才定稿保存",
            },
        ],
        "instructions": (
            "步骤预告（提高心理预期）：第一轮回复先向用户报完整菜单——"
            "「路线图分 6 步：① 起点判定 ② 目标拆解 ③ 阶段序列 ④ 逐阶段细化 "
            "⑤ 审计（第二意见） ⑥ 定稿交付」——报完再动手，禁止无预告直接执行。\n"
            "播报纪律：每个工具调用前用一句话告诉用户这步在干什么——全程禁止静默连调工具。\n"
            "请严格按照 step_template 的 6 步分步执行，禁止一步到位。\n"
            "1. 每步必须产出该步的 output 结构后再进入下一步；"
            "表格/清单必须带「为什么」（拆分的依据：真实 JD 要求/差距结果/证据缺口），只给结论不给理由不完整\n"
            "2. checkpoint=true 的步骤必须先把中间产物展示给用户确认，确认后再继续\n"
            "3. 起点判定可使用 start_level_rubric 作为参考，但不要把它当准入许可；"
            "等价证据（生产交付/开源/内推）同样有效\n"
            "4. 审计是第二意见：先 save_roadmap 保存雏形（结构校验通过即可），"
            "再调用 career-roadmap-auditor 并用 save_roadmap_audit 落库；审计不阻断定稿，"
            "FAIL 只用于硬矛盾，优先处理最多 3 条 must_fix，其余作为建议\n"
            "5. 过程中需要真实岗位数据时用 search_cases / fetch_company_jobs / fetch_jd_detail 获取，"
            "拿不到就 jd 占位（pending_user_import），绝不编造\n"
            "6. 最终调用 save_roadmap(roadmap_json) 保存；保存后向用户复述质量建议与未解决项；"
            "定稿产物除结构化数据外还有一份路线图 HTML 活地图，交付时要向用户说明它的用途与用法"
        ),
    })


_LEVEL_ORDER = {"暂不可入": 0, "小厂": 1, "中厂": 2, "大厂": 3}


def _level_rank(level: Any) -> int:
    """企业层级档位转数值（仅用于给出建议）。未知档位返回 -1。"""
    return _LEVEL_ORDER.get(str(level or "").strip(), -1)


def _advisory(code: str, message: str, checklist_id: str = "", severity: str = "note") -> dict:
    return {
        "code": code,
        "severity": severity,
        "checklist_id": checklist_id,
        "message": message,
    }


# 建议用 lint 词典（只提示，不阻塞保存）
_UMBRELLA_WORDS = ("专题", "批量", "全部", "汇总", "一批", "若干项")
_TIME_WORDS = ("每周", "每天", "每日", "一周内", "一天内", "半月内", "24小时", "24 小时", "月内", "日内")
_COUNT_RE = re.compile(r"\d+")


def _collect_roadmap_advisories(parsed: dict, profile) -> list[dict]:
    """收集路线图质量建议（不阻断保存）。

    代码只陈述可核对的事实与风险，是否修改由 LLM、审计员与用户决定。
    层级是命中率参考，不是准入许可；跨级只提示，不禁止。
    """
    advisories: list[dict] = []
    roadmap = parsed.get("roadmap", parsed)
    phases = [p for p in (roadmap.get("phases") or []) if isinstance(p, dict)]
    if not phases:
        return [_advisory("empty_phases", "路线图没有阶段，无法生成可执行任务。", "phase_fields")]

    start_level = str(
        roadmap.get("start_level", "") or (profile.gap or {}).get("start_level", "")
    ).strip()
    start_rank = _level_rank(start_level)
    if not start_level:
        advisories.append(_advisory(
            "missing_start_level",
            "未声明 start_level，无法给出层级跨度参考——可按用户实际证据判断起点。",
            "start_alignment",
        ))
    elif start_rank < 0:
        advisories.append(_advisory(
            "unknown_start_level",
            f"起点层级「{start_level}」无法识别（参考值：大厂/中厂/小厂/暂不可入），层级跨度判断已跳过。",
            "start_alignment",
        ))

    running_rank = start_rank
    running_name = start_level
    graduation_year = str((profile.who or {}).get("graduation_year", "") or "").strip()

    for phase in phases:
        phase_type = phase.get("type", "learn")
        name = phase.get("name", phase.get("id", "?"))
        target_level = str(phase.get("target_level", "") or "").strip()
        target_rank = _level_rank(target_level)
        kpi = phase.get("kpi") or {}

        if phase_type != "learn" and not str(phase.get("resume_value", "") or "").strip():
            advisories.append(_advisory(
                "missing_resume_value",
                f"阶段「{name}」没有简历价值（resume_value）——执行完无法写进简历。",
                "quantifiable",
            ))
        if isinstance(kpi, dict) and not (kpi.get("metric") and kpi.get("target")):
            advisories.append(_advisory(
                "missing_kpi",
                f"阶段「{name}」的 KPI 缺量化指标或目标值——无法判断是否完成。",
                "quantifiable",
            ))

        if target_level:
            if target_rank < 0:
                advisories.append(_advisory(
                    "unknown_target_level",
                    f"阶段「{name}」目标层级「{target_level}」无法识别，层级跨度判断已跳过。",
                    "level_continuity",
                ))
            elif running_rank >= 0 and target_rank > running_rank + 1:
                advisories.append(_advisory(
                    "level_jump",
                    f"阶段「{name}」目标层级「{target_level}」比当前起点「{running_name}」高 2 级以上——"
                    "请说明跨级依据（作品集/内推/前序交付证据）；层级只是命中率参考，不禁止投递。",
                    "level_continuity",
                ))

        # 届别：双向核对（不再只查「早于」）
        target_year = str(phase.get("graduation_year", "") or "").strip()
        if graduation_year and target_year:
            try:
                if int(target_year) != int(graduation_year):
                    advisories.append(_advisory(
                        "graduation_mismatch",
                        f"阶段「{name}」面向届 {target_year} 与用户毕业届 {graduation_year} 不一致，"
                        "请确认该岗位用户是否可投。",
                        "graduation_match",
                    ))
            except (TypeError, ValueError):
                advisories.append(_advisory(
                    "graduation_invalid",
                    f"阶段「{name}」的 graduation_year「{target_year}」不是有效年份。",
                    "graduation_match",
                ))

        # 复评升级：只对后续阶段生效，不写回 gap；提示复评标准
        after = str(phase.get("start_level_after", "") or "").strip()
        if after:
            if _level_rank(after) < 0:
                advisories.append(_advisory(
                    "unknown_start_level_after",
                    f"阶段「{name}」的 start_level_after「{after}」无法识别。",
                    "level_continuity",
                ))
            else:
                advisories.append(_advisory(
                    "start_level_after",
                    f"阶段「{name}」声明复评升级到「{after}」：请写清复评标准（evidence_gate/条件），"
                    "升级只影响后续阶段，不会自动改写差距分析起点。",
                    "level_continuity",
                ))
                running_rank = _level_rank(after)
                running_name = after

        # jd 三件套：只提示证据是否自洽
        jd_status = phase.get("jd_status", "not_required")
        jd = phase.get("jd")
        if phase_type != "learn":
            if jd and jd_status != "has_jd":
                advisories.append(_advisory(
                    "jd_status_mismatch",
                    f"阶段「{name}」填了 JD 细节但 jd_status={jd_status}——请确认是否来自真实数据。",
                    "jd_discipline",
                ))
            elif not jd and jd_status == "has_jd":
                advisories.append(_advisory(
                    "jd_missing",
                    f"阶段「{name}」标注 has_jd 但 jd 为空——请补真实 JD 或改为占位。",
                    "jd_discipline",
                ))
            elif jd_status == "pending_user_import" and not phase.get("confirmed"):
                advisories.append(_advisory(
                    "jd_pending_confirm",
                    f"阶段「{name}」的 JD 是占位，尚未得到用户确认。",
                    "jd_discipline",
                ))

    # 可执行性 lint：只扫里程碑/任务名，不扫阶段条件与目标
    for phase in phases:
        phase_name = phase.get("name", phase.get("id", "?"))
        for milestone in phase.get("milestones", []) or []:
            if not isinstance(milestone, dict):
                continue
            texts = [(milestone.get("name", ""), f"里程碑「{milestone.get('name', '')}」")]
            texts.extend(
                (task.get("name", ""), "任务")
                for task in (milestone.get("tasks") or [])
                if isinstance(task, dict)
            )
            for text, label in texts:
                text = str(text or "")
                time_hit = next((w for w in _TIME_WORDS if w in text), "")
                if time_hit:
                    advisories.append(_advisory(
                        "time_word",
                        f"阶段「{phase_name}」{label}「{text}」含时间词「{time_hit}」——"
                        "产品不排期，建议改为完成标准描述。",
                        "quantifiable",
                    ))
                umbrella_hit = next(
                    (w for w in _UMBRELLA_WORDS if w in text and not _COUNT_RE.search(text)),
                    "",
                )
                if umbrella_hit:
                    advisories.append(_advisory(
                        "umbrella_task",
                        f"阶段「{phase_name}」{label}「{text}」较笼统——建议拆成一次可完成的具体动作。",
                        "quantifiable",
                    ))

    # KPI 数字与任务计数不闭合（只提示）
    for phase in phases:
        kpi = phase.get("kpi")
        target = str((kpi or {}).get("target", "")) if isinstance(kpi, dict) else ""
        if not _COUNT_RE.search(target):
            continue
        phase_name = phase.get("name", phase.get("id", "?"))
        task_names = [
            str(t.get("name", ""))
            for m in phase.get("milestones", []) or [] if isinstance(m, dict)
            for t in m.get("tasks", []) or [] if isinstance(t, dict)
        ]
        if task_names and not any(_COUNT_RE.search(n) for n in task_names):
            advisories.append(_advisory(
                "kpi_task_count",
                f"阶段「{phase_name}」KPI 目标「{target}」带数字，但任务名都没有计数——"
                "验收时无法在任务层面累积。",
                "quantifiable",
            ))

    return advisories


def _roadmap_hash(parsed: dict) -> str:
    """路线图内容哈希：用于把审计记录绑定到具体版本。"""
    import hashlib

    payload = json.dumps(
        parsed.get("roadmap", parsed), ensure_ascii=False, sort_keys=True
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]



@mcp.tool()
def save_roadmap(roadmap_json: str, force: bool = False) -> str:
    """保存路线图到档案（只校验结构；质量项以建议形式返回，不阻断保存）。

    质量判断交给 LLM、审计员与用户：层级跨度、KPI、届别、可执行性等
    以 advisories 返回并持久化，不再拒绝保存；force 参数仅为兼容保留。

    Args:
        roadmap_json: 路线图的 JSON 字符串
        force: 已废弃，保留兼容（不再影响保存）

    Schema（与 sop/roadmap.yaml 一致）:
        {
            "strategy_summary": "整体策略说明",
            "start_level": "小厂",          // 可选：本次路线图使用的起点档位
            "phases": [                  // 阶段列表
                {
                    "type": "learn",              // learn/project/intern/research
                    "name": "基础学习",           // 阶段名称
                    "goal": "掌握基础",           // 阶段目标
                    "kpi": {"metric": "...", "target": "...", "evidence": "..."},
                    "resume_value": "",           // project/intern/research 必填
                    "target_level": "中厂",       // 本阶段目标层级（大厂/中厂/小厂/暂不可入），投递实习阶段必填
                    "start_level_after": "",      // 可选：复评升级后的起点档位（如 learn 阶段复评达标，后续阶段起点升为中厂）
                    "graduation_year": "",        // 可选：该阶段面向的毕业届（校招/实习阶段建议标注）
                    "condition": "",              // 可选：分支/备用路径说明（如「复评不达标则延长本阶段，改投中厂」）
                    "company": "XX公司",           // 目标公司名（公开常识，可直接写）
                    "rationale": "对双非友好",     // 推荐理由
                    "jd": null,                    // 具体 JD 细节——有真实数据（抓取/导入）才填
                    "jd_status": "not_required",   // has_jd / pending_user_import / not_required
                    "confirmed": false,            // 用户已确认「先占位后补JD」
                    "milestones": [               // 里程碑列表
                        {
                            "name": "Python 基础",        // 里程碑名称
                            "done_criteria": "能独立写出...", // 完成标准
                            "deliverable": "",             // 交付物
                            "tasks": [                     // 任务列表
                                {
                                    "name": "学习装饰器",      // 任务名称
                                    "description": "...",     // 可选
                                    "priority": "high"        // 可选
                                }
                            ]
                        }
                    ]
                }
            ]
        }

    注意：
    - 产品不规划时间：建议任务名不带时间节奏词（每周/每天等）；带时长描述会进建议清单，不阻断保存。
    - 知识光谱纪律：公司名是常识可自由写；JD 细节必须有真实数据，拿不到就 jd 置空 +
      jd_status=pending_user_import，用户确认后 confirmed 置 true。
    - 层级是命中率参考，不是准入许可：跨级会给出建议，由 LLM 结合证据（作品集/内推/前序交付）
      与用户判断，不禁止投递；start_level_after 只影响后续阶段的建议，不写回差距分析。
    - 返回值的 advisories 会持久化到档案，请在向用户交付时如实复述未解决项。
    """
    try:
        roadmap_data = _parse_json_param(roadmap_json, "路线图")
    except InvalidJsonError as exc:
        return error_response(exc.code, exc.message, exc.details)

    if not isinstance(roadmap_data, dict):
        return error_response(
            "INVALID_PARAM",
            "路线图必须是 JSON 对象（包含 roadmap/phases 字段）。",
            {"received": type(roadmap_data).__name__},
        )
    raw_phases = roadmap_data.get("roadmap", roadmap_data).get("phases")
    if raw_phases is not None and not isinstance(raw_phases, list):
        return error_response(
            "INVALID_PARAM",
            "phases 必须是数组。",
            {"received": type(raw_phases).__name__},
        )
    if raw_phases and any(not isinstance(phase, dict) for phase in raw_phases):
        return error_response(
            "INVALID_PARAM",
            "phases 的每一项必须是对象（阶段）。",
            {"received": [type(phase).__name__ for phase in raw_phases[:5]]},
        )

    profile = load_profile()
    parsed = parse_roadmap(json.dumps(roadmap_data, ensure_ascii=False))

    # 质量建议（不阻断保存）
    advisories = _collect_roadmap_advisories(parsed, profile)

    # 审计记录绑定路线图版本：内容变化只标记过期，不删除历史
    new_hash = _roadmap_hash(parsed)
    audit = dict(profile.audit or {})
    legacy_audit = (profile.plan or {}).get("audit") if isinstance(profile.plan, dict) else None
    if legacy_audit and not audit:
        audit = dict(legacy_audit)
    if audit and audit.get("roadmap_hash") and audit.get("roadmap_hash") != new_hash:
        audit["stale"] = True

    # 保存旧版本快照
    if profile.plan:
        save_plan_snapshot(source="before_roadmap")

    profile.plan = parsed
    profile.audit = audit
    profile.audited_phases = []
    profile.plan_saved_at = datetime.now().isoformat()
    profile.section_updated_at["plan"] = profile.plan_saved_at
    profile.touch()
    save_profile(profile)

    # 保存新版本快照
    save_plan_snapshot(source="roadmap_generated")

    # 格式化报告
    report = format_roadmap(parsed)

    # 定稿即交付：自动生成路线图活地图 HTML（随时可重新生成）
    map_path = ""
    try:
        map_html = _render_roadmap_map(profile)
        map_path = _write_html(map_html, kind="roadmap")
    except Exception:
        map_path = ""

    advisory_text = ""
    if advisories:
        advisory_text = "\n\n质量建议（不阻断保存，请向用户如实复述）：\n" + "\n".join(
            f"- [{a.get('checklist_id') or a['code']}] {a['message']}" for a in advisories
        )

    audit_note = ""
    if audit:
        verdict = audit.get("latest_verdict") or "未审计"
        stale = "（已过期：路线图内容已变化）" if audit.get("stale") else ""
        audit_note = f"\n\n审计记录：latest_verdict={verdict}{stale}（第二意见，不阻断定稿）。"

    return _json({
        "message": (
            f"路线图已保存。\n\n{report}{advisory_text}{audit_note}\n\n"
            f"路线图 HTML 已生成：{map_path}——双击即看，无需服务器；"
            "这是路线图的「活地图」（阶段/KPI/里程碑/任务全貌 + 勾选打卡，进度在浏览器本地保存），"
            "可随时用 export_dashboard(mode=\"roadmap\") 重新生成最新版。\n"
            "资产总览：双击 index.html（在 ~/CareerKit/ 下，报告/地图/仪表盘的统一入口）。\n"
            "向用户交付时先说明整条路线为什么这样排（阶段跨度/过渡理由），再给 HTML 路径。\n\n"
            "接下来调用 generate_tasks 生成任务列表；生成后引导用户按路线图开始第一阶段执行"
            "（或先 detail_current_phase 细化当前阶段的打卡路线）。"
        ),
        "next_steps": ["generate_tasks"],
        "context": {
            "phase": "roadmap_saved",
            "version": profile.version,
            "advisories": advisories,
            "audit": {
                "latest_verdict": audit.get("latest_verdict", ""),
                "stale": bool(audit.get("stale")),
                "fail_rounds": audit.get("fail_rounds", 0),
            },
            "accepted_risks": [],
        },
    })


@mcp.tool()
def save_roadmap_audit(audit_json: str) -> str:
    """保存路线图审计结果（第二意见；绑定当前路线图版本，不阻断定稿）。

    何时调用：career-roadmap-auditor 每完成一轮审计都要调用本工具落库。

    Args:
        audit_json: 审计结果的 JSON 字符串

    Schema:
        {
            "verdict": "PASS_WITH_NOTES",   // PASS / PASS_WITH_NOTES / FAIL（必填）
            "issues": [                     // FAIL 必填；PASS_WITH_NOTES 可带建议
                {"checklist_id": "start", "problem": "起点档位无打分依据", "fix": "补 rubric 评分"}
            ],
            "notes": ["非阻断建议"],         // 可选
            "summary": "一句话结论"          // 可选
        }

    纪律：FAIL 只用于硬矛盾（编造 JD、无依据跨级、KPI 完全缺失、届别硬冲突、
    任务不可打卡）；其余进 notes。审计记录按 roadmap_hash 绑定，路线图内容变化后
    自动标记过期，但不会阻断保存。
    """
    try:
        data = _parse_json_param(audit_json, "审计结果")
    except InvalidJsonError as exc:
        return error_response(exc.code, exc.message, exc.details)

    verdict = str(data.get("verdict", "")).strip().upper().replace("-", "_")
    if verdict not in ("PASS", "PASS_WITH_NOTES", "FAIL"):
        return error_response(
            "INVALID_PARAM",
            f"verdict 必须是 PASS / PASS_WITH_NOTES / FAIL，当前值：{verdict!r}",
            {"verdict": verdict},
        )
    issues = data.get("issues") or []
    if verdict == "FAIL" and not issues:
        return error_response(
            "INVALID_PARAM",
            "verdict=FAIL 时必须带 issues 明细（checklist_id/problem/fix），否则修正无从下手",
        )
    if not isinstance(issues, list):
        return error_response("INVALID_PARAM", "issues 必须是数组", {})
    notes = data.get("notes") or []
    if not isinstance(notes, list):
        notes = [str(notes)]

    profile = load_profile()
    if not (profile.plan or {}).get("roadmap"):
        return error_response(
            "MISSING_DATA",
            "档案里还没有路线图——请先 save_roadmap 保存雏形，再审计。",
            {"missing": "plan.roadmap"},
        )

    audit = dict(profile.audit or {})
    legacy = (profile.plan or {}).get("audit")
    if legacy and not audit:
        audit = dict(legacy)
    rounds = audit.get("rounds") or []
    if not isinstance(rounds, list):
        rounds = []

    now = datetime.now().isoformat()
    roadmap_hash = _roadmap_hash(profile.plan)
    entry = {
        "round": len(rounds) + 1,
        "verdict": verdict,
        "issues": issues if verdict in ("FAIL", "PASS_WITH_NOTES") else [],
        "notes": notes,
        "summary": str(data.get("summary", "") or "")[:200],
        "roadmap_hash": roadmap_hash,
        "saved_at": now,
    }
    fail_rounds = (audit.get("fail_rounds") or 0) + (1 if verdict == "FAIL" else 0)

    profile.audit = {
        "roadmap_hash": roadmap_hash,
        "rounds": rounds + [entry],
        "latest_verdict": verdict,
        "latest_issues": issues if verdict in ("FAIL", "PASS_WITH_NOTES") else [],
        "notes": notes,
        "fail_rounds": fail_rounds,
        "updated_at": now,
        "stale": False,
    }
    profile.touch()
    save_profile(profile)

    lines = [
        f"审计结果已落库（第 {entry['round']} 轮，verdict={verdict}）。",
        "审计是第二意见，不再阻断定稿：请把未解决项如实转告用户，由用户决定是否调整。",
    ]
    if verdict == "PASS":
        lines.append("审计通过：可以定稿。")
    elif verdict == "PASS_WITH_NOTES":
        lines.append("有建议但无硬矛盾：可以定稿；建议项见下，按需采纳。")
    else:
        lines.append(
            f"审计发现硬矛盾（累计 FAIL {fail_rounds} 轮）：建议先修正；"
            "定稿不被阻断，但请向用户明示这些风险。"
        )
        lines.append("请优先处理最多 3 条 must_fix，其余作为建议，避免无限重审。")
    for item in issues:
        if isinstance(item, dict):
            lines.append(
                f"- [{item.get('checklist_id', '?')}] {item.get('problem', '')} → {item.get('fix', '')}"
            )
    for note in notes[:10]:
        lines.append(f"- 建议：{note}")

    return _json({
        "message": "\n".join(lines),
        "next_steps": ["save_roadmap"],
        "context": {
            "round": entry["round"],
            "verdict": verdict,
            "fail_rounds": fail_rounds,
            "roadmap_hash": roadmap_hash,
        },
    })
