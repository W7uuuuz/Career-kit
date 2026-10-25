"""功能效果评估——不只判断是否报错，也量化规划/分析/产出的质量。

评分不是绝对真理，而是把「好计划应该具备什么」落成可回归的指标，
让每次改动都能看到质量变化，并直接输出可优化项。
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

TOOL_NAMES = {
    "start_session", "parse_resume", "intake", "finalize_profile",
    "import_jd", "import_jd_file", "list_profiles", "switch_profile",
    "delete_profile", "list_trash", "restore_profile", "explore_goals",
    "list_data_sources", "get_scraper_guide", "fetch_company_jobs",
    "fetch_jd_detail", "search_knowledge", "analyze_gaps",
    "save_gap_analysis", "generate_roadmap", "save_roadmap", "import_plan",
    "generate_tasks", "detail_current_phase", "save_current_detail",
    "get_next_tasks", "checkin_task", "trigger_insight", "apply_insight",
    "get_progress", "get_workflow_status", "export_dashboard",
}


@dataclass
class Metric:
    name: str
    score: float
    weight: float
    detail: str = ""


@dataclass
class QualityReport:
    name: str
    metrics: list[Metric] = field(default_factory=list)

    def add(self, name: str, score: float, weight: float, detail: str = "") -> None:
        self.metrics.append(Metric(name, _clamp(score), weight, detail))

    def extend(self, metrics: Iterable[Metric]) -> None:
        self.metrics.extend(metrics)

    @property
    def total(self) -> float:
        total_weight = sum(m.weight for m in self.metrics)
        if total_weight <= 0:
            return 0.0
        return round(sum(m.score * m.weight for m in self.metrics) / total_weight, 1)

    def verdict(self) -> str:
        total = self.total
        if total >= 85:
            return "优秀：可直接用于真实用户"
        if total >= 70:
            return "可用：有明确优化空间"
        if total >= 55:
            return "偏弱：需要重点优化"
        return "不合格：先修复质量问题"

    def findings(self) -> list[str]:
        return [
            f"{m.name} 仅 {m.score:.0f} 分：{m.detail}"
            for m in sorted(self.metrics, key=lambda x: x.score)
            if m.score < 70
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "total": self.total,
            "verdict": self.verdict(),
            "metrics": [
                {
                    "name": m.name,
                    "score": round(m.score, 1),
                    "weight": m.weight,
                    "detail": m.detail,
                }
                for m in self.metrics
            ],
            "findings": self.findings(),
        }


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, float(value)))


def _ratio(part: int, total: int, empty_score: float = 100.0) -> float:
    if total <= 0:
        return empty_score
    return part / total * 100


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def evaluate_profile(profile: dict[str, Any]) -> list[Metric]:
    who = _as_dict(profile.get("who"))
    have = _as_dict(profile.get("have"))
    want = _as_dict(profile.get("want"))

    skills = _as_list(have.get("skills"))
    verified = 0
    for skill in skills:
        if isinstance(skill, dict):
            if skill.get("evidence") and (
                skill.get("user_verified") or skill.get("verified")
            ):
                verified += 1
            elif skill.get("skill") and skill.get("evidence"):
                verified += 0.5
        elif isinstance(skill, str):
            continue
    evidence_score = _ratio(int(verified), len(skills), 60)

    specificity = 0.0
    if want.get("target_role"):
        specificity += 50
    for key in ("city", "salary", "target_companies", "industry"):
        if want.get(key):
            specificity += 12.5
    specificity = min(100, specificity)

    summary = 100 if (profile.get("summary") or "").strip() else 0
    who_score = 100 if who.get("name") and (who.get("status") or who.get("education")) else 60

    return [
        Metric("目标具体度", specificity, 4, f"target_role={want.get('target_role', '')!r}"),
        Metric("技能证据覆盖", evidence_score, 3, f"{int(verified)}/{len(skills)} 项带用户确认证据"),
        Metric("档案摘要", summary, 1, "有摘要，可跨会话交接" if summary else "缺少 summary"),
        Metric("身份信息", who_score, 2, "姓名与状态/教育已填写"),
    ]


def evaluate_gap(gap: dict[str, Any]) -> list[Metric]:
    gaps = [g for g in _as_list(gap.get("skill_gaps")) if isinstance(g, dict)]
    sourced = [g for g in gaps if str(g.get("source") or "").strip()]
    high = [g for g in gaps if g.get("priority") == "high"]

    actions = [a for a in _as_list(gap.get("priority_actions")) if isinstance(a, dict)]
    actionable_actions = [a for a in actions if a.get("action") or a.get("description")]
    red_flags = [r for r in _as_list(gap.get("resume_red_flags")) if isinstance(r, dict)]
    fixed_flags = [
        r for r in red_flags
        if (r.get("evidence_fix") or r.get("narrative_fix"))
    ]

    score = gap.get("match_score")
    score_valid = isinstance(score, (int, float)) and 0 <= score <= 100
    depth = 100 if len(gaps) >= 2 and high and gap.get("market_context") else (
        70 if len(gaps) >= 1 else 0
    )
    start_level = 100 if gap.get("start_level") else 50

    actionability = (
        0.6 * _ratio(len(actionable_actions), len(actions), 30)
        + 0.4 * _ratio(len(fixed_flags), len(red_flags), 80)
    )

    return [
        Metric("差距数据来源", _ratio(len(sourced), len(gaps), 0), 8, f"{len(sourced)}/{len(gaps)} 条带 source"),
        Metric("匹配度可用性", 100 if score_valid else 0, 3, f"match_score={score!r}"),
        Metric("差距深度", depth, 5, f"{len(gaps)} 条差距，{len(high)} 条高优先级"),
        Metric("行动建议可执行", actionability, 4, f"{len(actionable_actions)} 条行动，{len(fixed_flags)}/{len(red_flags)} 条红牌有对策"),
        Metric("起点层级", start_level, 3, f"start_level={gap.get('start_level', '')!r}"),
    ]


_TIME_KEYS = {"duration", "estimated_days", "deadline", "start_date", "end_date", "timeline"}


def _walk_keys(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key)
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


def evaluate_roadmap(roadmap: dict[str, Any], gap: dict[str, Any]) -> list[Metric]:
    phases = [p for p in _as_list(roadmap.get("phases")) if isinstance(p, dict)]
    milestones = [
        m for p in phases for m in _as_list(p.get("milestones")) if isinstance(m, dict)
    ]
    tasks = [
        t for m in milestones for t in _as_list(m.get("tasks")) if isinstance(t, dict)
    ]

    criteria = [m for m in milestones if str(m.get("done_criteria") or "").strip()]
    kpis = [
        p for p in phases
        if _as_dict(p.get("kpi")).get("metric") and _as_dict(p.get("kpi")).get("target")
    ]
    non_learn = [p for p in phases if p.get("type") != "learn"]
    resume_values = [p for p in non_learn if str(p.get("resume_value") or "").strip()]

    intern = [p for p in phases if p.get("type") == "intern"]
    jd_score = 0.0
    for phase in intern:
        status = phase.get("jd_status", "")
        if phase.get("jd") or status == "has_jd":
            jd_score += 100
        elif status == "pending_user_import" and phase.get("confirmed"):
            jd_score += 70
        elif status == "not_required":
            jd_score += 80

    names = [str(t.get("name") or "").strip() for t in tasks]
    sensible = [n for n in names if 4 <= len(n) <= 60]
    unique = len(set(names))

    time_fields = sorted({k for k in _walk_keys(roadmap) if k in _TIME_KEYS})

    alignment_score = 100
    start_rank = _level_rank(roadmap.get("start_level") or gap.get("start_level"))
    if start_rank >= 0:
        for phase in intern:
            target_rank = _level_rank(phase.get("target_level"))
            if target_rank >= 0 and target_rank > start_rank + 1:
                alignment_score = 30
            elif target_rank > start_rank:
                alignment_score = min(alignment_score, 75)

    phase_score = 100 if len(phases) >= 3 else 70 if len(phases) == 2 else 30 if phases else 0
    task_score = (
        0.7 * _ratio(len(sensible), len(names), 40)
        + 0.3 * _ratio(unique, len(names), 40)
    )

    return [
        Metric("阶段完整度", phase_score, 5, f"{len(phases)} 个阶段"),
        Metric("里程碑完成标准", _ratio(len(criteria), len(milestones), 40), 5, f"{len(criteria)}/{len(milestones)} 个有 done_criteria"),
        Metric("KPI 量化", _ratio(len(kpis), len(phases), 20), 4, f"{len(kpis)}/{len(phases)} 个阶段有 metric+target"),
        Metric("简历价值", _ratio(len(resume_values), len(non_learn), 50), 3, f"{len(resume_values)}/{len(non_learn)} 个非学习阶段有 resume_value"),
        Metric(
            "JD 依据",
            jd_score / len(intern) if intern else 100,
            4,
            f"{len(intern)} 个实习阶段中，真实 JD/已确认占位分别计分",
        ),
        Metric("任务具体度", task_score, 5, f"{len(sensible)}/{len(names)} 个任务名称具体，{len(set(names))} 个唯一"),
        Metric("无时间字段", 0 if time_fields else 100, 3, f"发现时间字段：{time_fields}" if time_fields else "无时长/截止日期字段"),
        Metric("起点层级连续", alignment_score, 1, "目标层级未跨越起点 +1"),
    ]


def evaluate_tasks(tasks: list[dict[str, Any]]) -> list[Metric]:
    tasks = [t for t in tasks if isinstance(t, dict)]
    bound = [t for t in tasks if t.get("phase_id")]
    # 空 checkin_mode 等价于 once（Task 模型默认值）
    modes = [
        t for t in tasks
        if t.get("checkin_mode") in ("", "once", "daily", "percent")
    ]
    names = [str(t.get("name") or "").strip() for t in tasks]
    duplicates = len(names) - len(set(n for n in names if n))
    completed = [t for t in tasks if t.get("status") == "completed"]
    invalid = [t for t in tasks if t.get("status") not in ("pending", "in_progress", "completed", "skipped")]

    return [
        Metric("任务绑定阶段", _ratio(len(bound), len(tasks), 40), 4, f"{len(bound)}/{len(tasks)} 个任务有 phase_id"),
        Metric("打卡点设计", _ratio(len(modes), len(tasks), 40), 4, f"{len(modes)}/{len(tasks)} 个任务有打卡模式"),
        Metric("任务去重", 100 if duplicates == 0 else max(0, 100 - duplicates * 20), 3, f"{duplicates} 个重名"),
        Metric("状态合法", 100 if not invalid else 0, 2, f"{len(invalid)} 个非法状态"),
        Metric(
            "执行可验证",
            100 if completed else 70,
            2,
            f"{len(completed)}/{len(tasks)} 已完成（用于验证打卡链路）",
        ),
    ]


def evaluate_guidance(responses: Iterable[Any]) -> list[Metric]:
    texts = [str(getattr(r, "text", r)) for r in responses]
    if not texts:
        return [Metric("下一步指引", 0, 5, "没有可评估的工具返回")]

    with_next = 0
    actionable = 0
    for text in texts:
        has_next = "next_steps" in text or "下一步" in text or "接下来" in text
        if has_next:
            with_next += 1
        if any(tool in text for tool in TOOL_NAMES):
            actionable += 1

    return [
        Metric("下一步指引", _ratio(with_next, len(texts), 30), 5, f"{with_next}/{len(texts)} 个返回含下一步"),
        Metric("指引可执行", _ratio(actionable, len(texts), 30), 5, f"{actionable}/{len(texts)} 个返回提到具体工具"),
    ]


def evaluate_dashboard(
    html: str,
    profile: dict[str, Any],
    *,
    require_snapshot: bool = True,
    require_interaction: bool = True,
    label: str = "",
) -> list[Metric]:
    snapshot = 'id="career-data"' in html
    snapshot_score = 100 if snapshot else (100 if not require_snapshot else 0)
    interaction = all(
        token in html for token in ("localStorage", "checkin_task", "export-btn", "reset-btn")
    )
    interaction_score = 100 if interaction else (100 if not require_interaction else 0)
    roadmap = _as_dict(_as_dict(profile.get("plan")).get("roadmap"))
    phase_names = [str(p.get("name") or "") for p in _as_list(roadmap.get("phases"))]
    rendered = sum(1 for name in phase_names if name and name in html)
    external = bool(
        re.search(r'<script[^>]+src=["\']https?://', html, re.I)
        or re.search(r'<link[^>]+href=["\']https?://', html, re.I)
    )

    prefix = f"{label}：" if label else ""
    return [
        Metric(
            prefix + "数据快照",
            snapshot_score,
            5,
            "内嵌 career-data JSON"
            if snapshot
            else ("进度视图使用服务端渲染" if not require_snapshot else "缺少数据快照"),
        ),
        Metric(
            prefix + "交互能力",
            interaction_score,
            5,
            "勾选/导出/重置/localStorage 齐全"
            if interaction
            else ("进度视图为静态快照" if not require_interaction else "交互元素不完整"),
        ),
        Metric(prefix + "阶段渲染", _ratio(rendered, len(phase_names), 50), 3, f"{rendered}/{len(phase_names)} 个阶段名进入 HTML"),
        Metric(prefix + "自包含", 0 if external else 100, 2, "存在外部脚本/样式" if external else "无外部依赖"),
    ]


def evaluate_dataset(
    rows: list[dict[str, Any]],
    details: list[dict[str, Any]],
    keyword: str = "",
) -> list[Metric]:
    rows = [r for r in rows if isinstance(r, dict) and not r.get("error")]
    if not rows:
        return [Metric("抓取字段完整", 0, 6, "没有有效结果")]

    required = ("title", "url", "company", "location")
    complete = sum(1 for r in rows if all(r.get(k) for k in required))
    urls = {r.get("url") for r in rows if r.get("url")}
    rich = sum(
        1 for d in details
        if isinstance(d, dict) and len(str(d.get("description") or d.get("content") or "")) >= 80
    )

    salaries = sum(1 for row in rows if str(row.get("salary") or "").strip())
    metrics = [
        Metric("抓取字段完整", _ratio(complete, len(rows), 0), 6, f"{complete}/{len(rows)} 条含 title/url/company/location"),
        Metric("结果去重", _ratio(len(urls), len(rows), 0), 3, f"{len(urls)}/{len(rows)} 个唯一 URL"),
        Metric("详情内容厚度", _ratio(rich, len(details), 0), 4, f"{rich}/{len(details)} 条详情正文 >= 80 字"),
        Metric(
            "薪资覆盖",
            _ratio(salaries, len(rows), 0),
            2,
            f"{salaries}/{len(rows)} 条含薪资（部分来源不公开）",
        ),
    ]
    if keyword:
        related = sum(
            1 for row in rows
            if keyword.lower() in json.dumps(row, ensure_ascii=False).lower()
        )
        metrics.append(
            Metric(
                "关键词相关性",
                _ratio(related, len(rows), 0),
                3,
                f"{related}/{len(rows)} 条命中「{keyword}」",
            )
        )
    return metrics


def _level_rank(level: Any) -> int:
    order = {"暂不可入": 0, "小厂": 1, "中厂": 2, "大厂": 3}
    return order.get(str(level or ""), -1)
