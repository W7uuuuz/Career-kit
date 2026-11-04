"""任务管理——任务创建、打卡辅助、阶段视图。

产品不规划时间：任务只有顺序和状态，进度以阶段为刻度。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..models import (
    CareerProfile,
    CheckIn,
    Task,
    TaskStatus,
)


def next_task_id(profile: CareerProfile) -> str:
    """生成不冲突的任务 ID：现有最大编号 + 1。"""
    max_num = 0
    for task in profile.tasks:
        if task.id.startswith("task_"):
            try:
                max_num = max(max_num, int(task.id[5:]))
            except ValueError:
                continue
    return f"task_{max_num + 1:03d}"


def create_tasks_from_roadmap(
    profile: CareerProfile,
    only_phase_ids: set[str] | None = None,
) -> list[Task]:
    """从路线图生成任务列表。

    任务 schema 与 sop/roadmap.yaml 的 output_schema 一致：
    {name, description, priority}。

    若当前阶段有详细路线（profile.plan.current_detail），按其打卡点
    （checkin_mode/checkin_goal）合并到对应任务（BUG-004）。

    Args:
        profile: 用户职业档案
        only_phase_ids: 只生成这些阶段的任务；None 表示全部阶段（兼容直接调用）

    Returns:
        生成的任务列表
    """
    roadmap = profile.plan.get("roadmap", profile.plan)
    phases = roadmap.get("phases", [])

    # 当前阶段的详细路线是权威任务清单：细化后直接替换该阶段任务，
    # 不再按任务名和里程碑做弱匹配（否则改名后的细化任务会被丢弃）。
    current_detail = profile.plan.get("current_detail") or {}
    detail_phase_id = str(current_detail.get("phase_id") or "")
    detail_tasks = [
        d for d in (current_detail.get("tasks") or [])
        if isinstance(d, dict) and d.get("name")
    ]

    # 稳定身份：同 phase + milestone + name 的任务在重建时复用旧 ID 与进度，
    # 避免 checkin / localStorage / 能力证据串到新任务上。
    existing = {
        (t.phase_id, t.milestone_id, t.name): t for t in profile.tasks
    }
    max_num = 0
    for task in profile.tasks:
        if task.id.startswith("task_"):
            try:
                max_num = max(max_num, int(task.id[5:]))
            except ValueError:
                continue
    counter = {"next": max_num}

    def _build(
        *,
        name: str,
        description: str,
        phase_id: str,
        milestone_id: str,
        priority: str,
        checkin_mode: str = "",
        checkin_goal: float = 0,
        how_to: list | None = None,
        resources: list | None = None,
        done_criteria: str = "",
    ) -> Task:
        old = existing.get((phase_id, milestone_id, name))
        if old is not None:
            return Task(
                id=old.id,
                name=name,
                description=description,
                phase_id=phase_id,
                milestone_id=milestone_id,
                status=old.status,
                priority=priority,
                started_at=old.started_at,
                completed_at=old.completed_at,
                checkin_mode=checkin_mode,
                checkin_goal=checkin_goal,
                checkin_progress=old.checkin_progress,
                how_to=list(how_to or []),
                resources=list(resources or []),
                done_criteria=done_criteria,
            )
        counter["next"] += 1
        return Task(
            id=f"task_{counter['next']:03d}",
            name=name,
            description=description,
            phase_id=phase_id,
            milestone_id=milestone_id,
            priority=priority,
            checkin_mode=checkin_mode,
            checkin_goal=checkin_goal,
            how_to=list(how_to or []),
            resources=list(resources or []),
            done_criteria=done_criteria,
        )

    tasks = []

    for phase_idx, phase in enumerate(phases):
        phase_id = phase.get("id") or f"phase_{phase_idx + 1}"
        if only_phase_ids is not None and phase_id not in only_phase_ids:
            continue
        phase_name = phase.get("name", f"阶段 {phase_idx + 1}")

        if detail_phase_id and phase_id == detail_phase_id and detail_tasks:
            for d in detail_tasks:
                tasks.append(_build(
                    name=str(d.get("name", "")),
                    description=str(d.get("description", "")),
                    phase_id=phase_id,
                    milestone_id=str(d.get("milestone_id", "")),
                    priority=str(d.get("priority", "medium")),
                    checkin_mode=str(d.get("checkin_mode", "")),
                    checkin_goal=float(d.get("checkin_goal", 0) or 0),
                    how_to=list(d.get("how_to") or []),
                    resources=list(d.get("resources") or []),
                    done_criteria=str(d.get("done_criteria") or ""),
                ))
            continue

        for ms_idx, milestone in enumerate(phase.get("milestones", [])):
            ms_name = milestone.get("name", f"里程碑 {ms_idx + 1}")
            ms_id = milestone.get("id") or f"{phase_id}_ms_{ms_idx + 1}"

            # 从里程碑的 tasks 字段生成任务
            for task_def in milestone.get("tasks", []):
                tasks.append(_build(
                    name=str(task_def.get("name", "")),
                    description=str(task_def.get("description", "")),
                    phase_id=phase_id,
                    milestone_id=ms_id,
                    priority=str(task_def.get("priority", "medium")),
                    checkin_mode=str(task_def.get("checkin_mode", "")),
                    checkin_goal=float(task_def.get("checkin_goal", 0) or 0),
                    how_to=list(task_def.get("how_to") or []),
                    resources=list(task_def.get("resources") or []),
                    done_criteria=str(task_def.get("done_criteria") or ""),
                ))

            # 如果里程碑没有 tasks 字段，用里程碑本身作为任务
            if not milestone.get("tasks"):
                tasks.append(_build(
                    name=ms_name,
                    description=str(milestone.get("description", "")),
                    phase_id=phase_id,
                    milestone_id=ms_id,
                    priority="medium",
                ))

        # 阶段没有任何可执行内容时，用阶段名兜底，保证阶段可追踪
        phase_task_count = sum(1 for t in tasks if t.phase_id == phase_id)
        if phase_task_count == 0:
            tasks.append(_build(
                name=f"推进阶段：{phase_name}",
                description=phase.get("goal", ""),
                phase_id=phase_id,
                milestone_id="",
                priority="medium",
            ))

    return tasks


def _already_checked_in_today(profile: CareerProfile, task_id: str) -> bool:
    today = datetime.now().date().isoformat()
    return any(
        c.task_id == task_id and str(c.timestamp)[:10] == today
        for c in profile.checkins
    )


def checkin_task(
    profile: CareerProfile,
    task_id: str,
    status: str = TaskStatus.COMPLETED,
    notes: str = "",
    amount: float = 0,
) -> tuple[CareerProfile, CheckIn]:
    """打卡任务。

    支持打卡方式（BUG-004，2026-11 统一协议）：
    - once（默认/空）：一次打卡即完成
    - daily：amount<=1 表示「今天打卡」，同一天只记一次；amount>1 表示目标天数
    - percent：amount 是目标百分比（绝对值），后端取 max(当前, amount)

    Args:
        profile: 用户职业档案
        task_id: 任务 ID
        status: 打卡状态（completed, skipped）
        notes: 备注
        amount: daily=1 或目标天数；percent=目标百分比（0-100）

    Returns:
        (更新后的档案, 打卡记录)
    """
    task = profile.get_task(task_id)
    if not task:
        raise ValueError(f"任务 {task_id} 不存在")

    skip_record = False

    # 更新任务状态
    if status == TaskStatus.SKIPPED:
        task.skip(notes)
    elif status == TaskStatus.COMPLETED:
        mode = task.checkin_mode or "once"
        if mode == "once":
            task.complete()
        elif mode == "daily":
            if amount > 1:
                # 绝对值：导入/同步历史进度时直接设目标天数
                task.checkin_progress = max(task.checkin_progress, float(amount))
            elif _already_checked_in_today(profile, task_id):
                # 同一天重复点击不累加
                skip_record = True
            else:
                task.checkin_progress += 1
            if task.checkin_goal > 0 and task.checkin_progress >= task.checkin_goal:
                task.complete()
            else:
                task.status = TaskStatus.IN_PROGRESS
        elif mode == "percent":
            target = amount if amount > 0 else task.checkin_progress
            task.checkin_progress = min(100.0, max(task.checkin_progress, float(target)))
            if task.checkin_goal > 0 and task.checkin_progress >= task.checkin_goal:
                task.complete()
            else:
                task.status = TaskStatus.IN_PROGRESS
        else:
            task.complete()
    else:
        raise ValueError(f"无效的打卡状态: {status}")

    # 创建打卡记录；同日重复打卡不落第二条
    checkin = CheckIn(
        task_id=task_id,
        status=status,
        notes=notes,
        amount=0 if skip_record else amount,
    )

    if not skip_record:
        profile.add_checkin(checkin)
    profile.touch()

    return profile, checkin


def record_capability_evidence(
    profile: CareerProfile,
    task: Task,
    notes: str = "",
) -> dict[str, Any]:
    """将完成任务沉淀为能力证据，写入 have.capability_evidence。

    用户完成的任务是真实水平的佐证，目标变更重新分析时自动成为输入。

    Returns:
        写入的证据条目
    """
    entry = {
        "task": task.name,
        "milestone": task.milestone_id,
        "completed_at": task.completed_at or "",
    }
    if notes:
        entry["notes"] = notes

    have = profile.have
    evidence_list = have.setdefault("capability_evidence", [])
    if isinstance(evidence_list, list):
        exists = any(
            isinstance(item, dict)
            and item.get("task") == entry["task"]
            and item.get("completed_at") == entry["completed_at"]
            for item in evidence_list
        )
        if not exists:
            evidence_list.append(entry)

    profile.section_updated_at["have"] = profile.updated_at
    return entry


def collect_completed_evidence(profile: CareerProfile) -> list[dict[str, Any]]:
    """把已完成/已跳过任务整理为能力证据条目（供调用方决定是否写入）。"""
    entries: list[dict[str, Any]] = []
    finished = [
        t for t in profile.tasks
        if t.status in (TaskStatus.COMPLETED, TaskStatus.SKIPPED)
    ]
    checkin_notes: dict[str, str] = {}
    for checkin in profile.checkins:
        checkin_notes.setdefault(checkin.task_id, checkin.notes)
    for task in finished:
        entry = {
            "task": task.name,
            "phase": task.phase_id,
            "status": task.status,
            "completed_at": task.completed_at or "",
        }
        notes = checkin_notes.get(task.id, "")
        if notes:
            entry["notes"] = notes
        entries.append(entry)
    return entries


def resolve_current_phase(profile: CareerProfile) -> dict[str, Any] | None:
    """唯一的当前阶段判定。

    规则：
    - 有任务：按路线图顺序找第一个存在未完成任务的阶段；全部完成返回 None。
    - 无任务：返回第一阶段（用于细化/预览），total=0。
    - 孤儿任务（phase_id 不在路线图）不参与判定。
    """
    roadmap = profile.plan.get("roadmap", profile.plan)
    phases = roadmap.get("phases", []) if isinstance(roadmap, dict) else []
    if not phases:
        return None

    finished = (TaskStatus.COMPLETED, TaskStatus.SKIPPED)
    phase_rows: list[dict[str, Any]] = []
    for idx, phase in enumerate(phases):
        phase_id = phase.get("id") or f"phase_{idx + 1}"
        phase_tasks = [t for t in profile.tasks if t.phase_id == phase_id]
        open_tasks = [t for t in phase_tasks if t.status not in finished]
        phase_rows.append({
            "phase_id": phase_id,
            "phase_name": phase.get("name", phase_id),
            "phase": phase,
            "tasks": phase_tasks,
            "open_tasks": open_tasks,
            "done": len(phase_tasks) - len(open_tasks),
            "total": len(phase_tasks),
        })

    if profile.tasks:
        for row in phase_rows:
            if row["open_tasks"]:
                return row
        # 当前阶段完成后，下一阶段的粗任务尚未生成：把它作为「当前阶段」，
        # 让 detail_current_phase / generate_tasks 能继续推进（P2-11）。
        for row in phase_rows:
            if row["total"] == 0:
                return row
        return None

    return phase_rows[0]


def current_phase_view(profile: CareerProfile) -> dict[str, Any] | None:
    """当前阶段的展示视图（兼容旧调用）。"""
    current = resolve_current_phase(profile)
    if current is None:
        return None
    return {
        "phase_id": current["phase_id"],
        "phase_name": current["phase_name"],
        "next_tasks": current["open_tasks"][:5],
        "done": current["done"],
        "total": current["total"],
    }


def format_task_playbook(task: Task, indent: str = "  ") -> list[str]:
    """把任务的执行 playbook 渲染成可读行（怎么做/资源/完成标准）。"""
    lines: list[str] = []
    if task.how_to:
        lines.append(f"{indent}怎么做：" + "；".join(str(s) for s in task.how_to))
    for item in task.resources or []:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "资源")
        url = str(item.get("url") or "")
        search = str(item.get("search") or "")
        if url:
            lines.append(f"{indent}资源：{label} {url}")
        elif search:
            lines.append(f"{indent}资源：{label}（搜索：{search}）")
    if task.done_criteria:
        lines.append(f"{indent}完成标准：{task.done_criteria}")
    return lines


def format_task_list(tasks: list[Task], title: str = "任务列表") -> str:
    """格式化任务列表。"""
    lines = [f"## {title}", ""]

    if not tasks:
        lines.append("暂无任务")
        return "\n".join(lines)

    # 按状态分组
    pending = [t for t in tasks if t.status == TaskStatus.PENDING]
    in_progress = [t for t in tasks if t.status == TaskStatus.IN_PROGRESS]
    completed = [t for t in tasks if t.status == TaskStatus.COMPLETED]
    skipped = [t for t in tasks if t.status == TaskStatus.SKIPPED]

    if in_progress:
        lines.append("### 进行中")
        for t in in_progress:
            lines.append(f"-  **{t.name}** (ID: {t.id})")
            lines += format_task_playbook(t)
        lines.append("")

    if pending:
        lines.append("### 待办")
        for t in pending:
            icon = {"high": "[高]", "medium": "[中]", "low": "[低]"}.get(t.priority, "[中]")
            lines.append(f"- {icon} **{t.name}** (ID: {t.id})")
            lines += format_task_playbook(t)
        lines.append("")

    if completed:
        lines.append("### 已完成")
        for t in completed:
            lines.append(f"-  {t.name}")
        lines.append("")

    if skipped:
        lines.append("### 已跳过")
        for t in skipped:
            lines.append(f"- {t.name}")
        lines.append("")

    return "\n".join(lines)


def format_progress_overview(profile: CareerProfile) -> str:
    """格式化进度概览——阶段优先，任务进度作为辅助。

    进度以阶段为刻度：新增任务不会让主进度倒退。
    """
    total = len(profile.tasks)
    completed = sum(1 for t in profile.tasks if t.status == TaskStatus.COMPLETED)
    in_progress = sum(1 for t in profile.tasks if t.status == TaskStatus.IN_PROGRESS)
    pending = sum(1 for t in profile.tasks if t.status == TaskStatus.PENDING)
    skipped = sum(1 for t in profile.tasks if t.status == TaskStatus.SKIPPED)
    finished = (TaskStatus.COMPLETED, TaskStatus.SKIPPED)

    task_pct = int(completed / total * 100) if total > 0 else 0
    task_bar = "█" * (task_pct // 5) + "░" * (20 - task_pct // 5)

    roadmap = profile.plan.get("roadmap", profile.plan)
    phases = roadmap.get("phases", []) if isinstance(roadmap, dict) else []

    if phases:
        rows = []
        done_phases = 0
        current_phase = None
        for phase in phases:
            phase_id = phase.get("id", "")
            name = phase.get("name") or phase_id or "未命名阶段"
            phase_tasks = [t for t in profile.tasks if t.phase_id == phase_id]
            done = sum(1 for t in phase_tasks if t.status in finished)
            is_done = bool(phase_tasks) and done == len(phase_tasks)
            if is_done:
                done_phases += 1
            elif current_phase is None:
                current_phase = (name, done, len(phase_tasks))
            rows.append((name, done, len(phase_tasks), is_done))

        phase_pct = int(done_phases / len(phases) * 100)
        phase_bar = "█" * (phase_pct // 5) + "░" * (20 - phase_pct // 5)
        lines = [
            f"## 阶段进度：{done_phases}/{len(phases)}（{phase_pct}%）[{phase_bar}]",
            "",
        ]
        for name, done, count, is_done in rows:
            mark = "[x]" if is_done else "[ ]"
            lines.append(f"- {mark} {name}（{done}/{count}）")
        if current_phase:
            name, done, count = current_phase
            lines += ["", f"当前阶段：{name}（{done}/{count}）"]
        else:
            lines += ["", "所有阶段已完成，可以回顾目标或规划下一程。"]
    else:
        lines = [
            f"## 整体进度：{task_pct}% [{task_bar}]",
            "",
        ]

    lines += [
        "",
        f"任务总计：已完成 {completed} / {total}（{task_pct}%）",
        f"-  进行中：{in_progress}",
        f"-  待办：{pending}",
    ]
    if skipped:
        lines.append(f"-  已跳过：{skipped}")
    lines += ["", f"共打卡 {len(profile.checkins)} 次", ""]

    return "\n".join(lines)
