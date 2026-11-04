"""自包含 HTML 渲染——进度仪表盘与交互式职业地图。

从 server.py 拆出，供 export_dashboard 与 save_roadmap 共用。

转义纪律：任务名/阶段名/JD 等均来自 LLM 生成或用户输入，插入 HTML 前
必须转义（Python 端 html.escape / JS 端 esc()）；内嵌 JSON 须防御
`</script>` 提前闭合（`</` → `<\\/`）。
"""

from __future__ import annotations

from datetime import datetime
from html import escape
from pathlib import Path

from .profile import get_active_profile_name
from .task_manager import resolve_current_phase

_FINISHED_STATUS = ("completed", "skipped")


def _format_jd_text(jd) -> str:
    """把阶段 JD 数据转成可读文本，避免把 Python 列表 repr 直接渲染到页面。"""
    if isinstance(jd, dict):
        samples = jd.get("samples")
        if isinstance(samples, list) and samples:
            lines: list[str] = []
            for sample in samples[:5]:
                if not isinstance(sample, dict):
                    lines.append(str(sample))
                    continue
                head = " · ".join(
                    str(sample.get(k)) for k in ("company", "title") if sample.get(k)
                )
                salary = sample.get("salary")
                if salary:
                    head = f"{head}（{salary}）" if head else str(salary)
                reqs = sample.get("requirements") or []
                req_text = (
                    "；".join(str(r) for r in list(reqs)[:8])
                    if isinstance(reqs, (list, tuple))
                    else str(reqs)
                )
                note = sample.get("note")
                line = head
                if req_text:
                    line += f"：{req_text}"
                if note:
                    line += f"（{note}）"
                lines.append(line.strip())
            return "\n".join(x for x in lines if x)
        return "；".join(
            f"{k}：{v}" for k, v in jd.items() if v and not isinstance(v, (list, dict))
        )
    return str(jd)


def _research_card_html(profile) -> str:
    """「市场调研」卡片：样本数、来源状态与报告入口（无调研时给引导）。"""
    research = getattr(profile, "research", None) or {}
    if not research.get("report_md"):
        return (
            "<p class='goal'>还没有调研报告。</p>"
            "<p>在建档后调用 research_market → gather_research_data 生成：真实 JD + "
            "同学历经历，全部带来源链接，落盘到你的 CareerKit 资产夹，随时可查证。</p>"
        )
    counts = research.get("counts") or {}
    fails = [
        s for s in (research.get("source_status") or []) if s.get("status") == "failed"
    ]
    fail_note = ""
    if fails:
        names = "、".join(str(s.get("source") or "?") for s in fails[:4])
        fail_note = f" <span class='meta'>失败源（如实标注）：{escape(names)}</span>"
    lines = (
        f"<p><b>岗位样本 {counts.get('jd_samples', 0)} 条 · 案例 {counts.get('cases', 0)} 条</b>"
        f"{fail_note}</p>"
        f"<p class='goal'>生成于 {escape(str(research.get('generated_at') or ''))} · "
        "每条带来源链接，可逐条验证；未获取的内容明确写了「未获取」。</p>"
    )
    links = []
    for label, key in (("阅读版", "report_html"), ("可读全文", "report_md"), ("资产总览", "index")):
        p = research.get(key)
        if p:
            encoded = Path(str(p)).as_uri()
            links.append(f"<a href='{encoded}'>{label}</a>")
    if links:
        lines += f"<p>{' · '.join(links)}</p>"
    return lines


def write_html(html: str, filename: str | None = None, kind: str = "analysis") -> str:
    """把 HTML 写入用户资产目录（自动分目录 + 刷新 index），返回文件路径。

    filename 缺省取该类型的固定名；kind: research/analysis/roadmap/progress。
    """
    profile_name = get_active_profile_name()
    if filename is None:
        from ..assets import ASSETS_FILENAME_BY_KIND

        filename = ASSETS_FILENAME_BY_KIND[kind]

    from ..assets import kind_assets_dir, rebuild_index

    target = kind_assets_dir(kind, profile_name) / filename
    target.write_text(html, encoding="utf-8")
    rebuild_index()
    return str(target)


def _weekly_card_html(profile) -> str:
    """「近 7 天」卡片：打卡/活跃/完成任务 + 窗口内投递增量（事实快照）。"""
    from .review import summarize_period

    facts = summarize_period(profile, days=7)
    if facts["checkin_count"]:
        exec_line = (
            f"打卡 {facts['checkin_count']} 次 · 活跃 {len(facts['active_days'])} 天"
            f" · 完成 {len(facts['completed'])} 个任务"
            + (f" · 跳过 {len(facts['skipped'])}" if facts["skipped"] else "")
        )
    else:
        days_since = facts["days_since_checkin"]
        exec_line = (
            f"窗口内无打卡（最近一次打卡在 {days_since} 天前）"
            if days_since is not None
            else "窗口内无打卡（尚无打卡记录）"
        )
    d = facts["funnel_delta"]
    funnel_line = (
        f"新投递 {d['new_applications']} · 进初筛 {d['screened']}"
        f" · 进面试 {d['interviewed']} · offer {d['offers']} · 拒信 {d['rejected']}"
        if facts["funnel_now"]["total"]
        else "投递：暂无记录"
    )
    return (
        f"<p><b>{escape(exec_line)}</b></p>"
        f"<p class='goal'>{escape(funnel_line)}</p>"
        "<p class='meta'>近 7 天为事实快照，不是考核——完整复盘用 get_weekly_review。</p>"
    )


def _funnel_card_html(profile) -> str:
    """「求职漏斗」卡片：事件口径的转化事实。"""
    from .application_tracker import funnel_stats

    stats = funnel_stats(profile)
    if not stats["total"]:
        return (
            "<p class='goal'>暂无投递记录——用户口述「投了」后用 record_application 登记事实。</p>"
        )
    rates = stats["rates"]

    def _pct(rate) -> str:
        return f"{int(rate * 100)}%" if isinstance(rate, (int, float)) else "-"

    line1 = (
        f"<p><b>投递 {stats['total']} → 过筛 {stats['screened']}（{_pct(rates['screen'])}）"
        f" → 面试 {stats['interviewed']}（{_pct(rates['interview'])}）"
        f" → offer {stats['offers']}（{_pct(rates['offer'])}）</b>"
        + ("" if stats["sample_sufficient"] else " <span class='meta'>（样本不足，仅供参考）</span>")
        + "</p>"
    )
    line2 = f"<p class='goal'>当前活跃 {stats['active']} · 已拒绝 {stats['rejected']} · 转化按事件历史统计（面试后被拒仍计入面试数）</p>"
    items = []
    _STATUS_LABELS = {
        "applied": "已投递", "screening": "进初筛", "interview": "进面试",
        "offer": "offer", "rejected": "已拒绝", "withdrawn": "已撤回",
    }
    for a in reversed(profile.applications[-5:]):
        label = _STATUS_LABELS.get(a.status, a.status)
        role = f" · {escape(a.role)}" if a.role else ""
        items.append(f"<li>{escape(a.company)}{role} <small>{label}</small></li>")
    if items:
        line2 += f"<ul class='apps-list'>{''.join(items)}</ul>"
    return line1 + line2


def render_progress_html(profile) -> str:
    """渲染进度仪表盘 HTML（mode="progress"）。"""
    total_tasks = len(profile.tasks)
    completed = sum(1 for t in profile.tasks if t.status == "completed")
    skipped = sum(1 for t in profile.tasks if t.status == "skipped")

    # 阶段视图
    roadmap = profile.plan.get("roadmap", profile.plan)
    phases_html = ""
    phases = roadmap.get("phases", []) if isinstance(roadmap, dict) else []
    for idx, phase in enumerate(phases):
        phase_id = phase.get("id") or f"phase_{idx + 1}"
        phase_tasks = [t for t in profile.tasks if t.phase_id == phase_id]
        done = sum(1 for t in phase_tasks if t.status in _FINISHED_STATUS)
        pct = int(done / len(phase_tasks) * 100) if phase_tasks else 0
        audited = "已审计" if phase_id in profile.audited_phases else ""
        phases_html += (
            f'<div class="phase"><div class="phase-head"><span>{escape(str(phase.get("name", phase_id)))}</span>'
            f'<span>{done}/{len(phase_tasks)}{audited}</span></div>'
            f'<div class="bar"><div class="fill" style="width:{pct}%"></div></div>'
            f'<p class="goal">{escape(str(phase.get("goal", "")))}</p></div>'
        )

    # 当前阶段任务
    current_html = "<p>暂无任务。</p>"
    open_tasks = [t for t in profile.tasks if t.status not in _FINISHED_STATUS]
    if open_tasks:
        items = "".join(
            f"<li>{escape(t.name)}{f' <small>({escape(t.phase_id)})</small>' if t.phase_id else ''}</li>"
            for t in open_tasks[:8]
        )
        current_html = f"<ul>{items}</ul>"

    # 能力证据
    evidence = profile.have.get("capability_evidence", [])
    ev_parts = []
    for e in evidence[-10:]:
        if not isinstance(e, dict):
            continue
        task = escape(str(e.get("task", "")))
        notes = f" — {escape(str(e['notes']))}" if e.get("notes") else ""
        ev_parts.append(f"<li><b>{task}</b>{notes}</li>")
    evidence_items = "".join(ev_parts) or "<li>暂无——完成任务打卡后自动沉淀</li>"
    evidence_html = f"<ul>{evidence_items}</ul>"

    # 调整历史
    adj_items = "".join(
        f"<li><b>{escape(a.timestamp[:10])}</b> {escape(a.reason or a.trigger)}</li>"
        for a in reversed(profile.adjustments[-5:])
    ) or "<li>暂无调整记录</li>"
    adjustments_html = f"<ul>{adj_items}</ul>"

    weekly_html = _weekly_card_html(profile)
    funnel_html = _funnel_card_html(profile)
    research_html = _research_card_html(profile)

    overall_pct = int(completed / total_tasks * 100) if total_tasks else 0

    current = resolve_current_phase(profile)
    current_phase_name = current["phase_name"] if current else ""
    summary = f"{len(phases)} 个阶段 · {completed}/{total_tasks} 个任务"
    if current_phase_name:
        summary += f" · 当前：{current_phase_name}"

    html = f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="career-kit-summary" content="{escape(summary)}">
<title>Career Kit 进度仪表盘</title>
<style>
body {{ font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif;
       max-width: 760px; margin: 0 auto; padding: 24px; color: #222; background: #fafafa; }}
h1 {{ font-size: 22px; }} h2 {{ font-size: 17px; border-bottom: 2px solid #4a90d9; padding-bottom: 4px; }}
.home {{ color: #4a90d9; text-decoration: none; font-size: 13px; }}
.home:hover {{ text-decoration: underline; }}
.card {{ background: #fff; border: 1px solid #e3e3e3; border-radius: 10px; padding: 16px; margin-bottom: 16px; }}
.bar {{ background: #eee; border-radius: 6px; height: 12px; overflow: hidden; }}
.fill {{ background: linear-gradient(90deg,#4a90d9,#67b26f); height: 100%; }}
.phase {{ margin-bottom: 14px; }}
.phase-head {{ display: flex; justify-content: space-between; font-size: 14px; margin-bottom: 4px; }}
.goal {{ color: #666; font-size: 13px; margin: 4px 0 0; }}
small, .meta {{ color: #999; font-size: 12px; }}
ul {{ padding-left: 20px; }} li {{ margin: 4px 0; font-size: 14px; }}
.overall {{ display: flex; align-items: center; gap: 12px; }}
.overall .num {{ font-size: 30px; font-weight: 700; color: #4a90d9; }}
</style>
</head>
<body>
<p><a class="home" href="../../index.html">← 返回资产中心</a></p>
<h1>Career Kit 进度仪表盘 <span class="meta">生成于 {datetime.now().strftime("%Y-%m-%d %H:%M")} · 快照 v{profile.version}</span></h1>

<div class="card overall"><span class="num">{overall_pct}%</span>
  <div style="flex:1"><div class="bar"><div class="fill" style="width:{overall_pct}%"></div></div>
  <p class="goal">共 {total_tasks} 个任务 · 完成 {completed} · 跳过 {skipped} · 目标：{escape(str(profile.want.get('target_role', '未设定')))}</p></div>
</div>

<div class="card"><h2>阶段进度（顺序推进，节奏自定）</h2>
{phases_html or '<p>尚未生成路线图。</p>'}</div>

<div class="card"><h2>接下来做</h2>{current_html}</div>

<div class="card"><h2>近 7 天</h2>{weekly_html}</div>

<div class="card"><h2>市场调研（来源真实）</h2>{research_html}</div>

<div class="card"><h2>求职漏斗</h2>{funnel_html}</div>

<div class="card"><h2>能力证据（来自打卡沉淀）</h2>{evidence_html}</div>

<div class="card"><h2>调整历史</h2>{adjustments_html}</div>

<p class="meta">顺序归产品，时间归用户 —— Career Kit 不为任务设定时限。</p>
</body></html>"""

    return html


def render_roadmap_map(profile) -> str:
    """渲染「职业地图」HTML（mode="roadmap"）：完整路线图 + 可交互打卡。

    自包含单文件：双击打开即用，无服务器依赖。
    - 本地控制台提供时（/roadmap）走 API，打卡直接写档案，刷新不丢；
    - file:// 离线打开时回退 localStorage，按档案名隔离，但移动目录/换浏览器会丢；
    - 任务勾选打卡、阶段导航、进度条实时联动；
    - 支持复制打卡指令与下载 JSON 备份，回传对话后由 checkin_task 同步档案。
    """
    import json as _json_lib

    roadmap = profile.plan.get("roadmap", profile.plan)
    phases = roadmap.get("phases", []) if isinstance(roadmap, dict) else []
    strategy = roadmap.get("strategy_summary", "")

    # 组装结构化数据（前端渲染 + localStorage 打卡）
    data = {
        "profile": get_active_profile_name(),
        "start_level": (profile.gap or {}).get("start_level", ""),
        "strategy": strategy,
        "all_complete": False,
        "phases": [],
    }
    phase_ids = [p.get("id") or f"phase_{i + 1}" for i, p in enumerate(phases)]
    current = resolve_current_phase(profile)
    current_phase_id = current["phase_id"] if current else None
    all_complete = bool(profile.tasks) and all(
        t.status in _FINISHED_STATUS for t in profile.tasks
    )
    if current_phase_id is None and phase_ids:
        # 全部完成时保留一个可见阶段（展示用，不代表“当前”）
        current_phase_id = phase_ids[-1]

    for idx, phase in enumerate(phases):
        phase_id = phase_ids[idx]
        phase_tasks = [t for t in profile.tasks if t.phase_id == phase_id]
        done = sum(1 for t in phase_tasks if t.status in _FINISHED_STATUS)
        total = len(phase_tasks)
        is_current = phase_id == current_phase_id and not all_complete

        jd_status = phase.get("jd_status", "not_required")
        confirmed = phase.get("confirmed", False)
        if jd_status == "has_jd":
            badge = "有 JD 依据"
            badge_cls = "ok"
        elif jd_status == "pending_user_import":
            badge = "待导入真实 JD" + ("（已确认）" if confirmed else "（待确认）")
            badge_cls = "warn"
        else:
            badge = "免 JD"
            badge_cls = ""

        jd = phase.get("jd")
        jd_text = ""
        if jd_status == "has_jd" and jd:
            jd_text = _format_jd_text(jd)

        kpi = phase.get("kpi", {}) or {}
        tasks = []
        for t in phase_tasks:
            tasks.append({
                "id": t.id,
                "name": t.name,
                "desc": t.description,
                "status": t.status,
                "priority": t.priority,
                "milestone_id": t.milestone_id,
                "checkin_mode": t.checkin_mode or "once",
                "checkin_goal": t.checkin_goal,
                "checkin_progress": t.checkin_progress,
                "how_to": list(t.how_to or []),
                "resources": list(t.resources or []),
                "done_criteria": t.done_criteria or "",
            })
        # 里程碑里的任务定义（未生成 task 时前端也能展示）
        milestone_tasks = []
        for ms in phase.get("milestones", []):
            for t in ms.get("tasks", []):
                milestone_tasks.append({
                    "name": t.get("name", ""),
                    "desc": t.get("description", ""),
                    "priority": t.get("priority", "medium"),
                    "done_criteria": t.get("done_criteria", ""),
                })

        ms_names = {ms.get("id"): ms.get("name", "") for ms in phase.get("milestones", [])}

        data["phases"].append({
            "id": phase_id,
            "name": phase.get("name", phase_id),
            "type": phase.get("type", "learn"),
            "goal": phase.get("goal", ""),
            "company": phase.get("company", ""),
            "rationale": phase.get("rationale", ""),
            "badge": badge,
            "badge_cls": badge_cls,
            "kpi_metric": kpi.get("metric", "") if isinstance(kpi, dict) else "",
            "kpi_target": kpi.get("target", "") if isinstance(kpi, dict) else "",
            "kpi_evidence": kpi.get("evidence", "") if isinstance(kpi, dict) else "",
            "resume_value": phase.get("resume_value", ""),
            "jd_text": jd_text,
            "done": done,
            "total": total,
            "is_current": is_current,
            "tasks": tasks,
            "milestone_tasks": milestone_tasks,
            "milestone_names": ms_names,
        })

    data["all_complete"] = all_complete
    total_tasks = sum(int(p.get("total") or 0) for p in data["phases"])
    done_tasks = sum(int(p.get("done") or 0) for p in data["phases"])
    current_name = next(
        (p["name"] for p in data["phases"] if p.get("is_current")), ""
    )
    summary = f"{len(data['phases'])} 个阶段 · {done_tasks}/{total_tasks} 个任务"
    if current_name:
        summary += f" · 当前：{current_name}"

    # 防御 `</script>` 提前闭合：JSON 中 `<\/` 与 `</` 等价，解析不受影响
    data_json = _json_lib.dumps(data, ensure_ascii=False).replace("</", "<\\/")

    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="career-kit-summary" content="{escape(summary)}">
<script>
  window.__CK_API__ = "__CK_API_BASE__";
  window.__CK_TOKEN__ = "__CK_TOKEN__";
</script>
<title>Career Kit 职业地图</title>
<style>
:root {{
  --bg: #f6f7fb; --card: #ffffff; --ink: #1f2430; --muted: #8a93a6;
  --line: #e6e9f0; --brand: #4a6cf7; --brand-soft: #eef1fe;
  --ok: #22a06b; --ok-soft: #e8f7f0; --warn: #b26a00; --warn-soft: #fff4e0;
  --radius: 14px; --shadow: 0 1px 3px rgba(31,36,48,.06), 0 4px 16px rgba(31,36,48,.05);
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif;
       background: var(--bg); color: var(--ink); line-height: 1.6; }}
.wrap {{ max-width: 980px; margin: 0 auto; padding: 28px 20px 60px; }}
header {{ display: flex; align-items: flex-end; justify-content: space-between;
          gap: 16px; flex-wrap: wrap; margin-bottom: 6px; }}
h1 {{ font-size: 24px; letter-spacing: .3px; }}
.home {{ color: var(--brand); text-decoration: none; font-size: 13px; }}
.home:hover {{ text-decoration: underline; }}
.mode-banner {{ margin: 8px 0 0; padding: 8px 12px; border-radius: 8px; font-size: 12.5px; }}
.mode-banner.online {{ background: var(--ok-soft); color: #146c43; }}
.mode-banner.offline {{ background: var(--warn-soft); color: var(--warn); }}
.meta {{ color: var(--muted); font-size: 12.5px; }}
.start {{ margin: 6px 0 18px; color: var(--muted); font-size: 13.5px; }}
.start b {{ color: var(--brand); }}
.strategy {{ background: var(--card); border: 1px solid var(--line); border-radius: var(--radius);
             padding: 14px 16px; margin: 12px 0 22px; color: #4a5160; font-size: 14px;
             box-shadow: var(--shadow); }}
/* 总进度 */
.overview {{ display: flex; gap: 18px; align-items: center; margin-bottom: 8px; flex-wrap: wrap; }}
.ring {{ --p: 0; width: 74px; height: 74px; border-radius: 50%;
         background: conic-gradient(var(--brand) calc(var(--p)*1%), #e6e9f0 0);
         display: grid; place-items: center; }}
.ring div {{ width: 58px; height: 58px; border-radius: 50%; background: var(--card);
             display: grid; place-items: center; font-weight: 700; font-size: 15px; color: var(--brand); }}
.overview-txt {{ font-size: 13.5px; color: var(--muted); }}
.overview-txt b {{ color: var(--ink); font-size: 15px; }}
/* 阶段导航 */
.tabs {{ display: flex; gap: 8px; flex-wrap: wrap; margin: 18px 0 16px; }}
.tab {{ padding: 8px 16px; border: 1px solid var(--line); background: var(--card);
        border-radius: 999px; font-size: 13.5px; cursor: pointer; color: var(--muted);
        transition: all .15s; }}
.tab:hover {{ border-color: var(--brand); color: var(--brand); }}
.tab.active {{ background: var(--brand); border-color: var(--brand); color: #fff; }}
.tab .tab-pct {{ margin-left: 6px; font-size: 12px; opacity: .8; }}
/* 阶段卡片 */
.card {{ background: var(--card); border: 1px solid var(--line); border-radius: var(--radius);
         padding: 20px 22px; margin-bottom: 16px; box-shadow: var(--shadow);
         display: none; }}
.card.active {{ display: block; }}
.card-head {{ display: flex; justify-content: space-between; align-items: flex-start;
              gap: 12px; flex-wrap: wrap; margin-bottom: 4px; }}
.card-title {{ font-size: 17px; font-weight: 700; }}
.type-pill {{ font-size: 11.5px; color: var(--muted); border: 1px solid var(--line);
             border-radius: 6px; padding: 1px 7px; margin-left: 8px; vertical-align: 2px; }}
.badge {{ display: inline-block; font-size: 11px; color: #666; background: #eee;
          border-radius: 8px; padding: 1px 7px; margin-left: 4px; }}
.badge.ok {{ color: var(--ok); background: var(--ok-soft); }}
.badge.warn {{ color: var(--warn); background: var(--warn-soft); }}
.cur-tag {{ color: var(--brand); font-size: 12px; margin-left: 8px; }}
.bar {{ background: #eef0f6; border-radius: 999px; height: 8px; overflow: hidden; margin: 10px 0 14px; }}
.fill {{ background: linear-gradient(90deg, var(--brand), #6f8bff); height: 100%; width: 0; transition: width .3s; }}
.done-txt {{ color: var(--muted); font-size: 12.5px; }}
.goal {{ color: #4a5160; font-size: 13.5px; margin: 6px 0; }}
.kpi {{ color: #5a6270; font-size: 13px; margin: 2px 0; }}
.resume {{ color: var(--ok); font-size: 13px; margin: 2px 0; }}
.jd {{ color: #455a64; background: #f4f7f8; padding: 8px 12px; border-radius: 8px;
      font-size: 12.5px; margin: 8px 0; white-space: pre-wrap; word-break: break-word; }}
.company {{ margin: 6px 0 2px; font-size: 13px; font-weight: 600; }}
/* 任务列表 */
.tasks {{ margin-top: 12px; border-top: 1px dashed var(--line); padding-top: 6px; }}
.task {{ display: flex; align-items: flex-start; gap: 10px; padding: 9px 4px;
         border-radius: 8px; cursor: pointer; }}
.task:hover {{ background: var(--brand-soft); }}
.task input {{ width: 18px; height: 18px; margin-top: 2px; accent-color: var(--brand); cursor: pointer; }}
.task-name {{ flex: 1; font-size: 13.5px; }}
.task-name.done {{ text-decoration: line-through; color: var(--muted); }}
.task-meta {{ color: var(--muted); font-size: 12px; }}
.task-detail {{ margin: 0 4px 10px 34px; font-size: 12.5px; color: #5a6270; }}
.task-detail summary {{ cursor: pointer; color: var(--brand); }}
.task-detail ol {{ margin: 6px 0 4px 18px; padding: 0; }}
.task-detail li {{ margin: 2px 0; }}
.task-done, .task-res {{ margin-top: 4px; }}
.task-res a {{ color: var(--brand); }}
.ms-preview {{ margin: 8px 0 0 18px; padding: 0; color: #5a6270; font-size: 12.5px; }}
.ms-preview li {{ margin: 4px 0; }}
.ck-ctl {{ color: var(--muted); font-size: 12px; display: inline-flex; align-items: center; gap: 6px; margin-right: 8px; }}
.ck-btn {{ padding: 3px 10px; border: 1px solid var(--brand); background: var(--brand-soft);
           color: var(--brand); border-radius: 8px; font-size: 12px; cursor: pointer; }}
.ck-btn:hover {{ background: var(--brand); color: #fff; }}
.ck-btn.ghost {{ background: transparent; border-color: var(--line); color: var(--muted); }}
.ck-btn.ghost:hover {{ border-color: var(--brand); color: var(--brand); background: transparent; }}
.done-badge {{ color: var(--ok); font-size: 12px; margin-right: 8px; font-weight: 600; }}
.ck-ctl input[type=range] {{ width: 110px; accent-color: var(--brand); }}
.ms {{ font-size: 12px; color: var(--muted); margin-top: 8px; font-weight: 600; }}
.pr {{ display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }}
.pr-high {{ background: #e5484d; }} .pr-medium {{ background: #f5a524; }} .pr-low {{ background: #22a06b; }}
.empty {{ color: var(--muted); font-size: 13px; padding: 8px 0; }}
/* 底部操作 */
.actions {{ position: sticky; bottom: 16px; display: flex; gap: 10px; justify-content: flex-end;
            margin-top: 18px; }}
.btn {{ padding: 9px 16px; border-radius: 10px; border: 1px solid var(--line);
        background: var(--card); font-size: 13px; cursor: pointer; color: var(--ink); }}
.btn.primary {{ background: var(--brand); border-color: var(--brand); color: #fff; }}
.btn:hover {{ opacity: .9; }}
.footer {{ text-align: center; color: var(--muted); font-size: 12px; margin-top: 30px; }}
.toast {{ position: fixed; left: 50%; bottom: 70px; transform: translateX(-50%);
         background: #1f2430; color: #fff; padding: 9px 18px; border-radius: 10px;
         font-size: 13px; opacity: 0; pointer-events: none; transition: opacity .25s; }}
.toast.show {{ opacity: 1; }}
@media (max-width: 640px) {{ .wrap {{ padding: 16px 12px 60px; }} }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <a class="home" href="../../index.html">← 返回资产中心</a>
      <h1>Career Kit 职业地图</h1>
    </div>
    <span class="meta">生成于 {datetime.now().strftime("%Y-%m-%d %H:%M")} · 路线图 v{profile.version}</span>
  </header>
  <div class="mode-banner" id="mode-banner"></div>

  <p class="start">起点层级：<b id="start-level">—</b>（差距分析产出，路线图按此对齐）</p>

  <div class="strategy" id="strategy">—</div>

  <div class="overview">
    <div class="ring" id="ring"><div id="ring-pct">0%</div></div>
    <div class="overview-txt">
      <div>总进度：<b id="total-pct">0%</b></div>
      <div id="total-done">已完成 0 / 0 个任务</div>
    </div>
  </div>

  <div class="tabs" id="tabs"></div>

  <div id="cards"></div>

  <div class="actions">
    <button class="btn" id="export-btn">复制打卡指令</button>
    <button class="btn" id="download-btn">下载打卡 JSON</button>
    <button class="btn" id="reset-btn">重置本地打卡</button>
  </div>

  <p class="footer">顺序归产品，时间归用户。离线打开时打卡存在浏览器 localStorage：移动目录、换浏览器或清理浏览器数据会丢失，建议用 <code>career-kit-serve</code> 控制台打开（直接写档案）。可复制打卡指令回传对话，或下载 JSON 备份。</p>
</div>
<div class="toast" id="toast"></div>

<script type="application/json" id="career-data">{data_json}</script>
<script>
(function () {{
  'use strict';
  var DATA = JSON.parse(document.getElementById('career-data').textContent);
  var KEY = 'career-kit-checkins-' + DATA.profile;
  // 由本地控制台提供时走 API（薄客户端）；直接用 file:// 打开时回退 localStorage
  var API = (window.__CK_API__ && String(window.__CK_API__).indexOf('__CK_') !== 0)
    ? String(window.__CK_API__).replace(/[/]$/, '') : null;
  var TOKEN = window.__CK_TOKEN__ || '';

  // HTML 转义：任务名/阶段名/JD 等来自 LLM 与用户输入，拼接进 innerHTML 前必须转义
  function esc(s) {{
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }}

  function loadCheckins() {{
    try {{ return JSON.parse(localStorage.getItem(KEY) || '{{}}'); }}
    catch (e) {{ return {{}}; }}
  }}
  function saveCheckins(c) {{ localStorage.setItem(KEY, JSON.stringify(c)); }}
  function apiCheckin(id, status, amount) {{
    return fetch(API + '/api/checkin', {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json', 'X-CK-Token': TOKEN }},
      body: JSON.stringify({{ task_id: id, status: status, amount: amount || 0 }})
    }}).then(function (res) {{
      if (!res.ok) throw new Error('同步失败（' + res.status + '）');
      return res.json();
    }});
  }}

  var checkins = API ? {{}} : loadCheckins();

  (function initMode() {{
    var banner = document.getElementById('mode-banner');
    if (API) {{
      banner.className = 'mode-banner online';
      banner.textContent = '已连接本地档案：打卡直接写入，刷新后仍保留。';
      var exportBtn = document.getElementById('export-btn');
      var resetBtn = document.getElementById('reset-btn');
      if (exportBtn) exportBtn.style.display = 'none';
      if (resetBtn) resetBtn.style.display = 'none';
    }} else {{
      banner.className = 'mode-banner offline';
      banner.textContent = '离线模式：打卡保存在此浏览器，需导出同步到档案。';
    }}
  }})();

  // 阶段初始状态：服务端已有 completed/skipped 的任务视为已打卡
  var phases = DATA.phases.map(function (ph) {{
    var tasks = ph.tasks.map(function (t) {{
      var serverDone = (t.status === 'completed' || t.status === 'skipped');
      var base = serverDone ? 'done' : 'open';
      // 服务端已完成优先；本地状态只覆盖未完成任务
      var st = serverDone ? 'done' : (checkins[t.id] || base);
      var mode = t.checkin_mode || 'once';
      return {{ id: t.id, name: t.name, desc: t.desc, priority: t.priority,
                 milestone_id: t.milestone_id, state: st, __server_done: serverDone,
                 mode: mode, goal: t.checkin_goal || 0,
                 progress: (checkins[t.id + ':progress'] != null
                   ? checkins[t.id + ':progress'] : (t.checkin_progress || 0)),
                 how_to: t.how_to || [], resources: t.resources || [],
                 done_criteria: t.done_criteria || '' }};
    }});
    return {{
      id: ph.id, name: ph.name, type: ph.type, goal: ph.goal,
      company: ph.company, rationale: ph.rationale, badge: ph.badge, badge_cls: ph.badge_cls,
      kpi_metric: ph.kpi_metric, kpi_target: ph.kpi_target, kpi_evidence: ph.kpi_evidence,
      resume_value: ph.resume_value, jd_text: ph.jd_text,
      is_current: ph.is_current, tasks: tasks, milestone_tasks: ph.milestone_tasks,
      milestone_names: ph.milestone_names || {{}},
      done: 0, total: tasks.length
    }};
  }});

  function render() {{
    document.getElementById('start-level').textContent = DATA.start_level || '未判定';
    document.getElementById('strategy').textContent = DATA.strategy || '—';
    var tabsEl = document.getElementById('tabs');
    var cardsEl = document.getElementById('cards');
    tabsEl.innerHTML = '';
    cardsEl.innerHTML = '';

    var totalDone = 0, totalAll = 0;
    phases.forEach(function (ph) {{
      var done = ph.tasks.filter(function (t) {{ return t.state === 'done'; }}).length;
      ph.done = done;
      totalDone += done; totalAll += ph.total;
      var pct = ph.total ? Math.round(done / ph.total * 100) : 0;
      ph.pct = pct;

      var tab = document.createElement('div');
      tab.className = 'tab' + (ph.is_current ? ' active' : '');
      tab.dataset.id = ph.id;
      tab.innerHTML = esc(ph.name) + '<span class="tab-pct">' + done + '/' + ph.total + ' · ' + pct + '%</span>';
      tabsEl.appendChild(tab);

      var badge = ph.badge ? '<span class="badge ' + esc(ph.badge_cls) + '">' + esc(ph.badge) + '</span>' : '';
      var cur = ph.is_current ? '<span class="cur-tag">[当前]</span>' : '';
      var company = ph.company ? '<div class="company">' + esc(ph.company)
        + (ph.rationale ? ' <span class="meta">— ' + esc(ph.rationale) + '</span>' : '') + '</div>' : '';
      var kpi = ph.kpi_metric
        ? '<div class="kpi">KPI：' + esc(ph.kpi_metric) + ' → ' + esc(ph.kpi_target)
          + (ph.kpi_evidence ? '（验证：' + esc(ph.kpi_evidence) + '）' : '') + '</div>' : '';
      var resume = ph.resume_value ? '<div class="resume">简历价值：' + esc(ph.resume_value) + '</div>' : '';
      var jd = ph.jd_text ? '<div class="jd">' + esc(ph.jd_text) + '</div>' : '';

      var tasksHtml = '';
      if (ph.tasks.length) {{
        var msStats = {{}};
        ph.tasks.forEach(function (t) {{
          if (!t.milestone_id) return;
          var s = msStats[t.milestone_id] || {{ done: 0, total: 0 }};
          s.total += 1;
          if (t.state === 'done') s.done += 1;
          msStats[t.milestone_id] = s;
        }});
        var lastMs = null;
        ph.tasks.forEach(function (t) {{
          var msLabel = '';
          if (t.milestone_id && t.milestone_id !== lastMs) {{
            lastMs = t.milestone_id;
            var ms = msStats[t.milestone_id] || {{ done: 0, total: 0 }};
            var msName = ph.milestone_names[t.milestone_id] || t.milestone_id.replace(/.*_ms_/, 'M');
            msLabel = '<div class="ms">里程碑：' + esc(msName)
              + '（' + ms.done + '/' + ms.total + '）</div>';
          }}
          var pr = {{ high: 'pr-high', medium: 'pr-medium', low: 'pr-low' }}[t.priority] || 'pr-medium';
          var nameCls = t.state === 'done' ? ' task-name done' : ' task-name';
          var tid = esc(t.id);
          var ctl = '';
          if (t.state === 'done') {{
            // 已完成：显示打勾状态 + 完成标记；本地打卡可撤销
            ctl = '<span class="done-badge">完成</span>'
              + (t.__server_done ? '' : ' <button class="ck-btn ghost" data-action="undo" data-id="'
                + tid + '">撤销</button>');
          }} else if (t.mode === 'daily') {{
            ctl = '<span class="ck-ctl" data-mode="daily" data-id="' + tid + '">'
              + '打卡 ' + Math.floor(t.progress) + '/' + (t.goal || '?') + ' 天'
              + ' <button class="ck-btn" data-action="daily" data-id="' + tid + '">今天打卡</button>'
              + '</span>';
          }} else if (t.mode === 'percent') {{
            ctl = '<span class="ck-ctl" data-mode="percent" data-id="' + tid + '">'
              + '进度 ' + Math.floor(t.progress) + '%/' + (t.goal || 100) + '%'
              + ' <input type="range" min="0" max="' + (t.goal || 100) + '" value="' + Math.floor(t.progress)
              + '" data-action="percent" data-id="' + tid + '" style="vertical-align:middle">'
              + '</span>';
          }} else {{
            ctl = '<input type="checkbox" data-action="once" data-id="' + tid + '">';
          }}
          var playbook = '';
          if (t.done_criteria) {{
            playbook += '<div class="task-done">完成标准：' + esc(t.done_criteria) + '</div>';
          }}
          if (t.how_to && t.how_to.length) {{
            playbook += '<ol class="task-how">' + t.how_to.map(function (h) {{
              return '<li>' + esc(h) + '</li>';
            }}).join('') + '</ol>';
          }}
          if (t.resources && t.resources.length) {{
            var resLinks = t.resources.map(function (r) {{
              var label = esc(r.label || '资源');
              if (r.url) {{
                return '<a href="' + esc(r.url) + '" target="_blank" rel="noopener">' + label + '</a>';
              }}
              if (r.search) {{
                return '<span>' + label + '（搜索：' + esc(r.search) + '）</span>';
              }}
              return '';
            }}).filter(Boolean).join(' · ');
            if (resLinks) playbook += '<div class="task-res">资源：' + resLinks + '</div>';
          }}
          var detail = playbook
            ? '<details class="task-detail"><summary>怎么做 / 完成标准</summary>' + playbook + '</details>'
            : '';
          tasksHtml += msLabel
            + '<div class="task-row">'
            + '<label class="task">'
            + ctl
            + '<span class="' + nameCls + '">'
            + '<span class="pr ' + pr + '"></span>' + esc(t.name) + '</span>'
            + '<span class="task-meta">' + tid + '</span>'
            + '</label>'
            + detail
            + '</div>';
        }});
      }} else if (ph.milestone_tasks.length) {{
        var preview = ph.milestone_tasks.map(function (m) {{
          var pr = {{ high: 'pr-high', medium: 'pr-medium', low: 'pr-low' }}[m.priority] || 'pr-medium';
          var done = m.done_criteria ? '：' + esc(m.done_criteria) : '';
          return '<li><span class="pr ' + pr + '"></span>' + esc(m.name) + done + '</li>';
        }}).join('');
        tasksHtml = '<div class="empty">里程碑已规划；细化当前阶段后会变成可打卡任务。</div>'
          + '<ul class="ms-preview">' + preview + '</ul>';
      }} else {{
        tasksHtml = '<div class="empty">暂无任务</div>';
      }}

      var card = document.createElement('div');
      card.className = 'card' + (ph.is_current ? ' active' : '');
      card.dataset.id = ph.id;
      card.innerHTML =
        '<div class="card-head"><span class="card-title">' + esc(ph.name)
          + '<span class="type-pill">' + esc(ph.type) + '</span>' + badge + cur + '</span>'
          + '<span class="done-txt">' + done + '/' + ph.total + ' · ' + pct + '%</span></div>'
        + '<div class="bar"><div class="fill" style="width:' + pct + '%"></div></div>'
        + company
        + (ph.goal ? '<div class="goal">' + esc(ph.goal) + '</div>' : '')
        + kpi + resume + jd
        + '<div class="tasks">' + tasksHtml + '</div>';
      cardsEl.appendChild(card);
    }});

    var totalPct = totalAll ? Math.round(totalDone / totalAll * 100) : 0;
    document.getElementById('ring').style.setProperty('--p', totalPct);
    document.getElementById('ring-pct').textContent = totalPct + '%';
    document.getElementById('total-pct').textContent = totalPct + '%';
    document.getElementById('total-done').textContent = DATA.all_complete
      ? '全部完成 · ' + totalDone + ' / ' + totalAll + ' 个任务'
      : '已完成 ' + totalDone + ' / ' + totalAll + ' 个任务';
    // 全部完成时没有“当前阶段”：仍展示第一张卡，但不打 [当前]
    if (!document.querySelector('.card.active') && cardsEl.firstChild) {{
      cardsEl.firstChild.classList.add('active');
      if (tabsEl.firstChild) tabsEl.firstChild.classList.add('active');
    }}
  }}

  function toast(msg) {{
    var t = document.getElementById('toast');
    t.textContent = msg; t.classList.add('show');
    setTimeout(function () {{ t.classList.remove('show'); }}, 1800);
  }}

  // 阶段导航
  document.getElementById('tabs').addEventListener('click', function (e) {{
    var tab = e.target.closest('.tab'); if (!tab) return;
    document.querySelectorAll('.tab').forEach(function (x) {{ x.classList.remove('active'); }});
    document.querySelectorAll('.card').forEach(function (x) {{ x.classList.remove('active'); }});
    tab.classList.add('active');
    document.querySelector('.card[data-id="' + tab.dataset.id + '"]').classList.add('active');
  }});

  // 任务打卡：once checkbox / daily 按钮 / percent 滑块
  function applyCheckin(id, mode, done, amount, isUndo) {{
    if (API) {{
      apiCheckin(id, isUndo ? 'pending' : 'completed', isUndo ? 0 : amount)
        .then(function () {{ location.reload(); }})
        .catch(function (err) {{ toast(err.message); }});
      return;
    }}
    var updated = false;
    phases.forEach(function (ph) {{
      ph.tasks.forEach(function (t) {{
        if (t.id === id) {{
          t.state = done ? 'done' : 'open';
          if (mode === 'daily' && done) t.progress = t.goal || 1;
          if (mode === 'percent') t.progress = amount;
          updated = true;
        }}
      }});
    }});
    if (updated) {{
      checkins[id] = done ? 'done' : 'open';
      checkins[id + ':progress'] = (mode === 'daily' || mode === 'percent') ? (amount || 0) : null;
      saveCheckins(checkins);
      render();
      toast(done ? '已打卡：' + id : '已更新进度：' + id);
    }}
  }}

  // click：once 完成勾选（点击任务行切换） / daily 打卡按钮
  document.getElementById('cards').addEventListener('click', function (e) {{
    var btn = e.target.closest('[data-action]');
    if (!btn) return;
    var action = btn.getAttribute('data-action');
    var id = btn.getAttribute('data-id');
    if (action === 'once') {{
      // 点击任务行（checkbox 外层 label）切换完成状态
      var t = null;
      phases.forEach(function (ph) {{
        ph.tasks.forEach(function (x) {{ if (x.id === id) t = x; }});
      }});
      if (!t) return;
      applyCheckin(id, 'once', t.state !== 'done', 1);
    }} else if (action === 'daily') {{
      var task = null;
      phases.forEach(function (ph) {{
        ph.tasks.forEach(function (x) {{ if (x.id === id) task = x; }});
      }});
      if (!task) return;
      // 当天打卡一次：进度 +1
      var newProg = (task.progress || 0) + 1;
      var goal = task.goal || 0;
      var doneNow = goal > 0 && newProg >= goal;
      task.progress = newProg;
      applyCheckin(id, 'daily', doneNow, doneNow ? goal : newProg);
    }} else if (action === 'undo') {{
      var task = null;
      phases.forEach(function (ph) {{
        ph.tasks.forEach(function (x) {{ if (x.id === id) task = x; }});
      }});
      if (!task) return;
      if ((task.mode || 'once') === 'daily') task.progress = 0;
      applyCheckin(id, task.mode || 'once', false, 0, true);
    }}
  }});

  // change：once checkbox 勾选 / percent 滑块
  document.getElementById('cards').addEventListener('change', function (e) {{
    var el = e.target;
    var action = el.getAttribute && el.getAttribute('data-action');
    var id = el.getAttribute && el.getAttribute('data-id');
    if (action === 'once' && el.matches('input[type=checkbox]')) {{
      applyCheckin(id, 'once', el.checked, 1);
    }} else if (action === 'percent' && el.matches('input[type=range]')) {{
      var val = parseFloat(el.value);
      var task = null;
      phases.forEach(function (ph) {{
        ph.tasks.forEach(function (x) {{ if (x.id === id) task = x; }});
      }});
      var goal = task ? (task.goal || 100) : 100;
      applyCheckin(id, 'percent', val >= goal, val);
    }}
  }});

  // 导出打卡数据（回传 LLM 同步档案，按打卡方式输出含 amount）
  document.getElementById('export-btn').addEventListener('click', function () {{
    var rows = [];
    phases.forEach(function (ph) {{
      ph.tasks.forEach(function (t) {{
        if (t.state === 'done' && !t.__server_done) {{
          if (t.mode === 'daily') {{
            rows.push('checkin_task(task_id="' + t.id + '", status="completed", amount=' + (t.goal || 1) + ')');
          }} else if (t.mode === 'percent') {{
            rows.push('checkin_task(task_id="' + t.id + '", status="completed", amount=' + (t.progress || 0) + ')');
          }} else {{
            rows.push('checkin_task(task_id="' + t.id + '", status="completed")');
          }}
        }} else if (t.state !== 'done' && (t.mode === 'daily' || t.mode === 'percent') && t.progress > 0) {{
          // 部分进度：导出累计打卡
          rows.push('checkin_task(task_id="' + t.id + '", status="completed", amount=' + (t.progress || 0) + ')');
        }}
      }});
    }});
    var text = rows.length ? rows.join('\\n') : '（暂无打卡记录）';
    var pre = document.createElement('textarea');
    pre.value = text; document.body.appendChild(pre); pre.select();
    try {{ document.execCommand('copy'); toast('已复制 ' + rows.length + ' 条打卡指令'); }}
    catch (err) {{ prompt('复制以下打卡指令回传对话：', text); }}
    pre.remove();
  }});

  // 下载打卡 JSON 备份（不依赖 localStorage 存活）
  document.getElementById('download-btn').addEventListener('click', function () {{
    var payload = {{
      profile: DATA.profile,
      exported_at: new Date().toISOString(),
      source: API ? 'career-kit-serve' : 'localStorage',
      checkins: checkins
    }};
    var blob = new Blob([JSON.stringify(payload, null, 2)], {{ type: 'application/json' }});
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'career-kit-checkins-' + (DATA.profile || 'default') + '.json';
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(function () {{ URL.revokeObjectURL(a.href); }}, 1000);
    toast('已下载打卡 JSON 备份');
  }});

  // 重置本地打卡
  document.getElementById('reset-btn').addEventListener('click', function () {{
    if (!confirm('确认清除本浏览器的打卡记录？（仅本地，不影响档案）')) return;
    checkins = {{}};
    phases.forEach(function (ph) {{
      ph.tasks.forEach(function (t) {{
        // 只重置用户本地勾选，服务端已完成的（初始 done）保持完成
        if (t.state === 'done' && !t.__server_done) t.state = 'open';
      }});
    }});
    saveCheckins(checkins); render(); toast('已重置本地打卡');
  }});

  render();
}})();
</script>
</body></html>"""
