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

_FINISHED_STATUS = ("completed", "skipped")


def write_html(html: str, filename: str) -> str:
    """把 HTML 写入临时目录并返回路径。"""
    import tempfile

    out_path = Path(tempfile.gettempdir()) / filename
    out_path.write_text(html, encoding="utf-8")
    return str(out_path)


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

    overall_pct = int(completed / total_tasks * 100) if total_tasks else 0

    html = f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>Career Kit 进度仪表盘</title>
<style>
body {{ font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif;
       max-width: 760px; margin: 0 auto; padding: 24px; color: #222; background: #fafafa; }}
h1 {{ font-size: 22px; }} h2 {{ font-size: 17px; border-bottom: 2px solid #4a90d9; padding-bottom: 4px; }}
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
<h1>Career Kit 进度仪表盘 <span class="meta">生成于 {datetime.now().strftime("%Y-%m-%d %H:%M")} · 快照 v{profile.version}</span></h1>

<div class="card overall"><span class="num">{overall_pct}%</span>
  <div style="flex:1"><div class="bar"><div class="fill" style="width:{overall_pct}%"></div></div>
  <p class="goal">共 {total_tasks} 个任务 · 完成 {completed} · 跳过 {skipped} · 目标：{escape(str(profile.want.get('target_role', '未设定')))}</p></div>
</div>

<div class="card"><h2>阶段进度（顺序推进，节奏自定）</h2>
{phases_html or '<p>尚未生成路线图。</p>'}</div>

<div class="card"><h2>接下来做</h2>{current_html}</div>

<div class="card"><h2>能力证据（来自打卡沉淀）</h2>{evidence_html}</div>

<div class="card"><h2>调整历史</h2>{adjustments_html}</div>

<p class="meta">顺序归产品，时间归用户 —— Career Kit 不为任务设定时限。</p>
</body></html>"""

    return html


def render_roadmap_map(profile) -> str:
    """渲染「职业地图」HTML（mode="roadmap"）：完整路线图 + 可交互打卡。

    自包含单文件：双击打开即用，无服务器依赖。
    - 任务勾选打卡：点击 checkbox 标记完成/取消，状态持久化到浏览器 localStorage
    - 进度实时更新：阶段/总进度条随勾选联动
    - 阶段导航：顶部 tab 点击切换当前查看的阶段
    - 导出打卡数据：一键复制 JSON，粘贴回对话让 LLM 用 checkin_task 同步到档案
    重新生成时保留已打卡记录（localStorage 按档案名隔离）。
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
        "phases": [],
    }
    for idx, phase in enumerate(phases):
        phase_id = phase.get("id") or f"phase_{idx + 1}"
        phase_tasks = [t for t in profile.tasks if t.phase_id == phase_id]
        done = sum(1 for t in phase_tasks if t.status in _FINISHED_STATUS)
        total = len(phase_tasks)
        is_current = bool(profile.tasks) and phase_id == profile.tasks[0].phase_id

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
            if isinstance(jd, dict):
                jd_text = "；".join(f"{k}：{v}" for k, v in jd.items() if v)
            else:
                jd_text = str(jd)

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
            })
        # 里程碑里的任务定义（未生成 task 时前端也能展示）
        milestone_tasks = []
        for ms in phase.get("milestones", []):
            for t in ms.get("tasks", []):
                milestone_tasks.append({
                    "name": t.get("name", ""),
                    "desc": t.get("description", ""),
                    "priority": t.get("priority", "medium"),
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

    # 防御 `</script>` 提前闭合：JSON 中 `<\/` 与 `</` 等价，解析不受影响
    data_json = _json_lib.dumps(data, ensure_ascii=False).replace("</", "<\\/")

    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
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
      font-size: 12.5px; margin: 8px 0; }}
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
.ck-ctl {{ color: var(--muted); font-size: 12px; display: inline-flex; align-items: center; gap: 6px; margin-right: 8px; }}
.ck-btn {{ padding: 3px 10px; border: 1px solid var(--brand); background: var(--brand-soft);
           color: var(--brand); border-radius: 8px; font-size: 12px; cursor: pointer; }}
.ck-btn:hover {{ background: var(--brand); color: #fff; }}
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
    <h1>Career Kit 职业地图</h1>
    <span class="meta">生成于 {datetime.now().strftime("%Y-%m-%d %H:%M")} · 路线图 v{profile.version}</span>
  </header>

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
    <button class="btn" id="export-btn">导出打卡数据</button>
    <button class="btn" id="reset-btn">重置本地打卡</button>
  </div>

  <p class="footer">顺序归产品，时间归用户。勾选任务即本地打卡（浏览器保存）；点「导出打卡数据」把打卡结果粘贴回对话，即可同步到档案。</p>
</div>
<div class="toast" id="toast"></div>

<script type="application/json" id="career-data">{data_json}</script>
<script>
(function () {{
  'use strict';
  var DATA = JSON.parse(document.getElementById('career-data').textContent);
  var KEY = 'career-kit-checkins-' + DATA.profile;

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

  var checkins = loadCheckins();

  // 阶段初始状态：服务端已有 completed/skipped 的任务视为已打卡
  var phases = DATA.phases.map(function (ph) {{
    var tasks = ph.tasks.map(function (t) {{
      var serverDone = (t.status === 'completed' || t.status === 'skipped');
      var base = serverDone ? 'done' : 'open';
      var st = checkins[t.id] || base;
      var mode = t.checkin_mode || 'once';
      return {{ id: t.id, name: t.name, desc: t.desc, priority: t.priority,
                 milestone_id: t.milestone_id, state: st, __server_done: serverDone,
                 mode: mode, goal: t.checkin_goal || 0,
                 progress: (t.checkin_progress || 0) }};
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
      var jd = ph.jd_text ? '<div class="jd">' + esc(ph.jd_text.slice(0, 400)) + '</div>' : '';

      var tasksHtml = '';
      if (ph.tasks.length) {{
        var lastMs = null;
        ph.tasks.forEach(function (t) {{
          var msLabel = '';
          if (t.milestone_id && t.milestone_id !== lastMs) {{
            lastMs = t.milestone_id;
            msLabel = '<div class="ms">里程碑：' + esc(ph.milestone_names[t.milestone_id] || t.milestone_id.replace(/.*_ms_/, 'M')) + '</div>';
          }}
          var pr = {{ high: 'pr-high', medium: 'pr-medium', low: 'pr-low' }}[t.priority] || 'pr-medium';
          var nameCls = t.state === 'done' ? ' task-name done' : ' task-name';
          var tid = esc(t.id);
          var ctl = '';
          if (t.state === 'done') {{
            // 已完成：显示打勾状态 + 完成标记
            ctl = '<span class="done-badge">完成</span>';
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
          tasksHtml += msLabel
            + '<label class="task">'
            + ctl
            + '<span class="' + nameCls + '">'
            + '<span class="pr ' + pr + '"></span>' + esc(t.name) + '</span>'
            + '<span class="task-meta">' + tid + '</span>'
            + '</label>';
        }});
      }} else if (ph.milestone_tasks.length) {{
        tasksHtml = '<div class="empty">里程碑已规划（任务列表生成后即可打卡）</div>';
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
    document.getElementById('total-done').textContent = '已完成 ' + totalDone + ' / ' + totalAll + ' 个任务';
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
  function applyCheckin(id, mode, done, amount) {{
    var updated = false;
    phases.forEach(function (ph) {{
      ph.tasks.forEach(function (t) {{
        if (t.id === id) {{
          t.state = done ? 'done' : 'open';
          if (mode === 'daily') t.progress = done ? (t.goal || 1) : (t.progress || 0);
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
