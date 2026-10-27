"""市场调研报告——把批量抓取的真实数据渲染成用户可读的三件套并落盘。

纪律：报告正文 100% 代码渲染自抓取数据，不经 LLM 之手——「来源真实」的硬保证。
落盘位置走 assets.py（用户资产目录）：调研报告/<日期_方向>.{md,html,json}，
同时刷新档案的 research 字段与 index.html 资产中心。
"""

from __future__ import annotations

import json
from datetime import datetime
from html import escape
from typing import Any

from .assets import (
    next_asset_stem,
    rebuild_index,
    write_asset_text,
)
from .research_digest import build_digest
from .tools.profile import get_active_profile_name, load_profile, save_profile

# 展示层预览长度（表格单元用）；报告结构与 json 保留原文，不再二次截断
_PREVIEW_LIMIT = 160

_REPORT_CSS = """
:root { --ink:#1f2430; --muted:#6b7280; --line:#e5e7eb; --bg:#f6f7fb; --accent:#2563eb; }
* { box-sizing:border-box; }
body { margin:0; font-family:"Segoe UI","Microsoft YaHei",system-ui,sans-serif;
       color:var(--ink); background:var(--bg); }
main { max-width:920px; margin:0 auto; padding:24px 20px 60px; }
h1 { font-size:22px; margin:8px 0 4px; }
.sub { color:var(--muted); font-size:13px; margin-bottom:18px; }
h2 { font-size:17px; margin:28px 0 10px; padding-left:10px; border-left:4px solid var(--accent); }
table { width:100%; border-collapse:collapse; background:#fff; font-size:13.5px; }
th, td { border:1px solid var(--line); padding:8px 10px; text-align:left;
         vertical-align:top; }
th { background:#f1f3f9; font-weight:600; }
td a { color:var(--accent); text-decoration:none; }
.pill { display:inline-block; font-size:12px; border-radius:6px; padding:2px 8px;
        margin:2px 4px 2px 0; }
.pill.ok { background:#dcfce7; color:#166534; }
.pill.fail { background:#fee2e2; color:#991b1b; }
.note { background:#fffbeb; border:1px solid #fde68a; border-radius:8px; padding:10px 14px;
        font-size:13px; color:#713f12; }
.compact { color:var(--muted); font-size:12.5px; }
details.jd { background:#fff; border:1px solid var(--line); border-radius:8px;
             padding:8px 12px; margin:8px 0; }
details.jd summary { cursor:pointer; }
details.jd p { margin:8px 0; line-height:1.6; }
footer { margin-top:40px; color:var(--muted); font-size:12.5px; }
footer a { color:var(--accent); }
"""


def _one_line(text: Any) -> str:
    """多行文本压成单行（md 表格/面板用，不裁剪内容）。"""
    return " ".join(str(text or "").split())


def _preview(text: Any, limit: int = _PREVIEW_LIMIT) -> str:
    """表格预览：只在渲染层截断，完整原文在 json 与「岗位详情」区。"""
    s = _one_line(text)
    if len(s) <= limit:
        return s
    return s[: limit - 1] + "…"


def _clip(text: Any, limit: int) -> str:
    """短字段裁剪（标题/地点/薪资/来源等），长正文一律保留原文。"""
    s = str(text or "").strip()
    if len(s) <= limit:
        return s
    return s[: limit - 1] + "…"


def build_report(profile: Any, gathered: dict[str, Any]) -> dict[str, Any]:
    """把 gather 的抓取结果清洗为报告结构。

    纪律：报告结构（含 json）保留原文，展示裁剪只在渲染层做——
    「摘要被截断」的实测反馈正是二次裁剪叠加导致的（复测 BUG #1）。

    gathered 期望结构（research_tools.gather_research_data 产出）：
    {
        "direction": str, "city": str, "education_tag": str,
        "jd_families": [ {slug, label, rows, status, error, elapsed,
                          dropped_no_detail, dropped_titles} ],
        "cases_result": collect_cases 的返回 {"cases", "warnings", "sources"},
    }
    """
    direction = str(gathered.get("direction") or "").strip()
    city = str(gathered.get("city") or "").strip()
    education_tag = str(gathered.get("education_tag") or "").strip()

    want = profile.want or {}
    who = profile.who or {}
    have = profile.have or {}
    context = {
        # direction 显式传入时优先于档案 want（复测 BUG #7：多方向调研标题不能串档）
        "goal": _clip(direction or want.get("target_role") or "", 80),
        "city": city or _clip(want.get("city") or who.get("city") or "", 40),
        "education": education_tag
        or _clip(who.get("education") or who.get("education_tag") or "", 40),
        "resume_trust": _clip(
            (have.get("self_assessment") or {}).get("resume_trust", ""), 20
        ),
    }

    jd_samples: list[dict[str, Any]] = []
    source_status: list[dict[str, Any]] = []
    dropped_no_detail = 0
    dropped_gaps: list[dict[str, str]] = []
    for family in gathered.get("jd_families") or []:
        rows = family.get("rows") or []
        status = family.get("status") or ("ok" if rows else "empty")
        if family.get("error"):
            status = "failed"
        dropped = int(family.get("dropped_no_detail") or 0)
        dropped_no_detail += dropped
        label = family.get("label") or family.get("slug") or "未知来源"
        source_status.append(
            {
                "source": label,
                "scope": "jd",
                "status": status,
                "count": len(rows),
                "elapsed": round(float(family.get("elapsed") or 0), 1),
                "error": _one_line(family.get("error") or ""),
                "dropped_no_detail": dropped,
            }
        )
        if dropped:
            titles = family.get("dropped_titles") or []
            dropped_gaps.append(
                {
                    "missing": f"来源「{label}」有 {dropped} 条岗位未获取到详情，已剔除",
                    "reason": "详情接口无正文/失败或需要登录",
                    "suggestion": (
                        "剔除示例：" + "、".join(titles[:3]) + "；"
                        if titles
                        else ""
                    ) + "检查该源登录态，或改用手头 JD 用 import_jd 补充",
                }
            )
        fetched_at = datetime.now().strftime("%Y-%m-%d %H:%M")
        for row in rows:
            if not isinstance(row, dict) or row.get("error"):
                continue
            jd_samples.append(
                {
                    "company": _clip(row.get("company") or label, 40),
                    "title": _clip(row.get("title"), 120),
                    "location": _clip(row.get("location"), 60),
                    "salary": _clip(row.get("salary"), 40),
                    "snippet": str(row.get("summary") or "").strip(),
                    "description": str(row.get("description") or "").strip(),
                    "requirements": str(row.get("requirements") or "").strip(),
                    "detail_status": row.get("detail_status") or "ok",
                    "source": _clip(row.get("source") or family.get("slug"), 20),
                    "url": str(row.get("url") or "").strip(),
                    "fetched_at": fetched_at,
                }
            )
    # 花名册 id：父/子 agent 按 id 选择深读（read_research_details）
    for idx, sample in enumerate(jd_samples, 1):
        sample["id"] = f"JD{idx:02d}"
    cases_result = gathered.get("cases_result") or {}
    case_sources = cases_result.get("sources") or {}
    case_warnings = cases_result.get("warnings") or []
    # 复测 BUG #5：JD 源与案例源分开统计——案例源也进状态面板（失败如实入缺口）
    for slug, raw_count in case_sources.items():
        count = int(raw_count or 0)
        error = ""
        for warning in case_warnings:
            text = str(warning)
            if text.startswith(f"{slug}:"):
                error = _one_line(text.split(":", 1)[1].strip())
                break
        if slug == "local" and count == 0 and not error:
            continue  # 本地知识库为空是常态，不当作「来源无结果」计入缺口
        if count > 0:
            status = "ok"
        elif error:
            status = "failed"
        else:
            status = "empty"
        source_status.append(
            {
                "source": f"案例·{slug}",
                "scope": "cases",
                "status": status,
                "count": count,
                "elapsed": 0.0,
                "error": error,
            }
        )

    # 本地已抓 JD 与本次 JD 表去重：同一岗位不在「同背景经历」里重复出现（复测 BUG #2）
    jd_urls = {sample["url"] for sample in jd_samples if sample["url"]}
    jd_titles = {
        _norm_title(sample["title"]) for sample in jd_samples if sample["title"]
    }

    raw_cases = cases_result.get("cases") or []
    cases: list[dict[str, Any]] = []
    for case in raw_cases:
        if not isinstance(case, dict) or case.get("error"):
            continue
        bg = case.get("background") or {}
        case_url = str(case.get("url") or "").strip()
        case_title = _clip(case.get("title"), 120)
        if case.get("origin") == "local_jd" and (
            (case_url and case_url in jd_urls) or _norm_title(case_title) in jd_titles
        ):
            continue
        cases.append(
            {
                "kind": _clip(case.get("kind"), 30),
                "title": case_title,
                "education_tag": _clip(bg.get("education_tag"), 20),
                "year": _clip(bg.get("year"), 12),
                "company": _clip(bg.get("company"), 30),
                "position": _clip(bg.get("position"), 30),
                "highlights": [
                    str(h).strip() for h in (case.get("highlights") or [])[:3] if str(h).strip()
                ],
                "hit_terms": [_clip(h, 12) for h in (case.get("hit_terms") or [])[:4]],
                "salary": _clip(case.get("salary"), 40),
                "location": _clip(case.get("location"), 60),
                "source": _clip(case.get("source"), 20),
                "url": case_url,
                "local_path": str(case.get("local_path") or ""),
                "date": _clip(case.get("date"), 20),
                "match_score": case.get("match_score"),
            }
        )

    for idx, case in enumerate(cases, 1):
        case["id"] = f"CS{idx:02d}"

    digest = build_digest(
        jd_samples, cases, dropped_no_detail, raw_case_count=len(raw_cases)
    )

    gaps = _derive_gaps(jd_samples, cases, source_status)
    gaps = dropped_gaps + gaps

    counts = {
        "jd_samples": len(jd_samples),
        "cases": len(cases),
        "cases_raw": len(raw_cases),
        "cases_filtered": max(0, len(raw_cases) - len(cases)),
        "dropped_no_detail": dropped_no_detail,
        "source_ok": sum(1 for s in source_status if s["status"] == "ok"),
        "source_fail": sum(1 for s in source_status if s["status"] == "failed"),
        "source_empty": sum(1 for s in source_status if s["status"] == "empty"),
    }

    return {
        "type": "research_report",
        "direction": direction,
        "city": city,
        "education_tag": education_tag,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "context": context,
        "jd_samples": jd_samples,
        "cases": cases,
        "source_status": source_status,
        "case_warnings": [_one_line(w) for w in case_warnings][:10],
        "gaps": gaps,
        "digest": digest,
        "counts": counts,
    }


def _norm_title(text: Any) -> str:
    """标题归一化（去空白/大小写）——本地 JD 与本次 JD 去重用。"""
    return "".join(str(text or "").lower().split())


def _derive_gaps(
    jd_samples: list[dict[str, Any]],
    cases: list[dict[str, Any]],
    source_status: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """自动生成数据缺口清单——不猜测，只陈述没拿到什么与建议补偿方式。"""
    gaps: list[dict[str, str]] = []
    for s in source_status:
        if s["status"] == "failed":
            gaps.append(
                {
                    "missing": f"来源「{s['source']}」本次未获取到数据",
                    "reason": _one_line(s["error"]) or "抓取失败",
                    "suggestion": "见来源状态面板；必要时提供手头 JD 用 import_jd 补充",
                }
            )
        elif s["status"] == "empty":
            gaps.append(
                {
                    "missing": f"来源「{s['source']}」未搜到匹配岗位",
                    "reason": "查询词与该源无匹配，或岗位详情均不可用",
                    "suggestion": "换关键词重跑，或补充手头 JD",
                }
            )
    if jd_samples and not any(j.get("salary") for j in jd_samples):
        gaps.append(
            {
                "missing": "全部岗位样本均无薪资数据",
                "reason": "当前可用来源不公开薪资",
                "suggestion": "可在对话中补充 BOSS直聘等含薪来源后重跑调研",
            }
        )
    if not cases:
        gaps.append(
            {
                "missing": "未搜到同背景成功经历案例",
                "reason": "各案例源本次无匹配（或查询过于具体）",
                "suggestion": "放宽学历/方向词重试；或先走 import_jd 导入手头材料",
            }
        )
    return gaps


def _md_link(label: str, url: str) -> str:
    if not url:
        return label
    return f"[{label}]({url})"


def render_markdown(report: dict[str, Any]) -> str:  # noqa: C901
    """报告 markdown 版（数据全量来自抓取；未获取的如实写缺口）。"""
    ctx = report.get("context") or {}
    counts = report.get("counts") or {}
    lines: list[str] = []
    lines.append(
        f"# 市场调研报告 · {report.get('direction') or ctx.get('goal') or '未命名方向'}"
    )
    lines.append("")
    lines.append(
        f"> 生成于 {report.get('generated_at')} ｜ 数据来自实时抓取与本地知识库，"
        "每条附来源；未获取到的内容明确标注，不使用 AI 记忆编造。"
    )
    lines.append("")
    ctx_parts = []
    if ctx.get("goal"):
        ctx_parts.append(f"目标：{ctx['goal']}")
    if ctx.get("city"):
        ctx_parts.append(f"城市：{ctx['city']}")
    if ctx.get("education"):
        ctx_parts.append(f"学历：{ctx['education']}")
    if ctx.get("resume_trust"):
        ctx_parts.append(f"简历信任度：{ctx['resume_trust']}")
    if ctx_parts:
        lines.append("## 〇、调研上下文（取自你的档案）")
        lines.append("")
        lines.append("｜ ".join(ctx_parts))
        lines.append("")

    jds = report.get("jd_samples") or []
    lines.append(f"## 一、真实岗位样本（{len(jds)} 条，目标公司 + 同方向对照）")
    lines.append("")
    if jds:
        lines.append("| 公司 | 岗位 | 地点 | 薪资 | 摘要（预览） | 来源 | 抓取 |")
        lines.append("|---|---|---|---|---|---|---|")
        for j in jds:
            source = _md_link(j.get("source") or "来源", j.get("url", ""))
            preview = j.get("description") or j.get("requirements") or j.get("snippet") or ""
            lines.append(
                f"| {j.get('company','')} | {_md_escape_md(j.get('title',''))} "
                f"| {j.get('location','')} "
                f"| {j.get('salary') or '未获取'} | {_md_escape_md(_preview(preview, 120))} "
                f"| {source} | {j.get('fetched_at','')} |"
            )
        lines.append("")
        lines.append("### 岗位详情（完整 JD，无需跳转）")
        lines.append("")
        for idx, j in enumerate(jds, 1):
            lines.append(
                f"#### {idx}. {j.get('company','')} · {_md_escape_md(j.get('title',''))}"
            )
            meta_bits = [
                str(bits) for bits in (
                    j.get("location"), j.get("salary") or "薪资未获取",
                    j.get("source"), j.get("fetched_at"),
                ) if str(bits or "").strip()
            ]
            if meta_bits:
                lines.append("｜".join(meta_bits))
            if j.get("url"):
                lines.append(f"来源：{j['url']}")
            description = str(j.get("description") or "").strip()
            requirements = str(j.get("requirements") or "").strip()
            if description:
                lines.append("")
                lines.append(f"**岗位描述**：{_md_block(description)}")
            if requirements:
                lines.append("")
                lines.append(f"**任职要求**：{_md_block(requirements)}")
            if not description and not requirements:
                lines.append("详情未获取——见后文「数据缺口」。")
            lines.append("")
    else:
        lines.append("未获取到岗位样本（见后文「数据缺口」）——不猜测。")
    lines.append("")

    cases = report.get("cases") or []
    success = [c for c in cases if c.get("kind") == "success_experience"]
    require = [c for c in cases if c.get("kind") != "success_experience"]
    lines.append(
        f"## 二、同背景经历（{len(cases)} 条：成功经验 {len(success)} · 面试要求 {len(require)}）"
    )
    lines.append("")
    if cases:
        for c in cases:
            tag_bits = [
                bits
                for bits in (
                    c.get("education_tag"),
                    c.get("year"),
                )
                if bits
            ]
            tag_text = " · ".join(tag_bits)
            path_bits = [
                bits
                for bits in (
                    c.get("company"),
                    c.get("position"),
                )
                if bits
            ]
            path_text = " · ".join(str(b) for b in path_bits)
            hl = "；".join(c.get("highlights") or [])
            source = _md_link(c.get("source") or "来源", c.get("url", ""))
            lines.append(
                f"- **{_md_escape_md(c.get('title',''))}**"
                + (f"（{tag_text}）" if tag_text else "")
                + (f"｜{path_text}" if path_text else "")
                + (f"｜{c.get('salary')}" if c.get("salary") else "")
                + f"｜{source}"
                + (f"｜{c.get('date')}" if c.get("date") else "")
            )
            if hl:
                lines.append(f"  - 要点：{_md_escape_md(hl)}")
            if c.get("hit_terms"):
                lines.append(f"  - 命中：{'、'.join(c['hit_terms'])}")
        match = [c.get("match_score") for c in cases if isinstance(c.get("match_score"), (int, float))]
        if match:
            lines.append("")
            lines.append("*排序依据：与你的学历档匹配度优先，其次时效。*")
    else:
        lines.append("未获取到同背景案例——不硬凑。")
    lines.append("")

    lines.append("## 三、来源状态面板（失败也如实展示）")
    lines.append("")
    lines.append("| 来源 | 状态 | 条数 | 耗时(秒) | 备注 |")
    lines.append("|---|---|---|---|---|")
    for s in report.get("source_status") or []:
        status_text = {"ok": "成功", "failed": "失败", "empty": "无结果"}.get(
            s.get("status"), s.get("status", "")
        )
        note_bits = [_md_escape_md(s.get("error", "") or "—")]
        if s.get("dropped_no_detail"):
            note_bits.append(f"（剔除 {s['dropped_no_detail']} 条无详情岗位）")
        lines.append(
            f"| {s.get('source','')} | {status_text} | {s.get('count',0)} "
            f"| {s.get('elapsed',0)} | {' '.join(note_bits)} |"
        )
    warnings = report.get("case_warnings")
    if warnings:
        lines.append("")
        for w in warnings:
            lines.append(f"- 案例源提示：{_md_escape_md(w)}")
    lines.append("")

    gaps = report.get("gaps") or []
    lines.append("## 四、数据缺口与建议")
    lines.append("")
    if gaps:
        for g in gaps:
            lines.append(f"- **{_md_escape_md(g.get('missing',''))}**"
                         f"（{_md_escape_md(g.get('reason',''))}）——"
                         f"{_md_escape_md(g.get('suggestion',''))}")
    else:
        lines.append("本次调研没有明显缺口。")
    lines.append("")
    counts_text = "，".join(
        f"{counts.get(k)} {label}" for k, label in
        (("jd_samples", "条岗位"), ("cases", "条案例")) if counts.get(k) is not None
    )
    lines.append(
        f"---\n样本统计：{counts_text}。原始数据在同名 .json；本报告及全部来源"
        "可在资产中心（index.html）直达。本报告由抓取数据代码渲染生成，"
        "未使用 AI 记忆编造。"
    )
    return "\n".join(lines)


def _md_escape_md(text: str) -> str:
    return str(text).replace("|", "\\|") if text else ""


def _md_block(text: str) -> str:
    """多行正文 → markdown 硬换行块（保留完整内容，不裁剪）。"""
    lines = [line.rstrip() for line in str(text).strip().splitlines() if line.strip()]
    return "  \n".join(lines)


def _html_text(text: Any) -> str:
    """多行正文 → 转义 + <br>（完整内容，不裁剪）。"""
    escaped = escape(str(text or "")).strip()
    return escaped.replace("\r\n", "\n").replace("\n", "<br>")


def render_html(report: dict[str, Any]) -> str:
    """报告 HTML 阅读版（同 dashboard 视觉风格；底部返回资产中心）。"""
    ctx = report.get("context") or {}
    jds = report.get("jd_samples") or []
    cases = report.get("cases") or []
    parts: list[str] = []
    parts.append(
        f"<h1>{escape('市场调研报告 · ' + (report.get('direction') or ctx.get('goal') or '未命名方向'))}</h1>"
        f'<p class="sub">生成于 {escape(str(report.get("generated_at","")))} ｜ '
        "数据来自实时抓取与本地知识库，每条附来源；未获取到的内容明确标注，"
        "不使用 AI 记忆编造。</p>"
    )

    ctx_bits = " ｜ ".join(
        escape(str(v)) for v in (ctx.get("goal"), ctx.get("city"), ctx.get("education")) if v
    )
    if ctx_bits:
        parts.append(f"<h2>调研上下文</h2><p>{ctx_bits}</p>")

    parts.append(f"<h2>一、真实岗位样本（{len(jds)} 条）</h2>")
    if jds:
        rows = []
        for j in jds:
            source_inner = (
                f'<a href="{escape(j["url"], quote=True)}">{escape(str(j.get("source") or "来源"))}</a>'
                if j.get("url")
                else escape(str(j.get("source") or ""))
            )
            preview = j.get("description") or j.get("requirements") or j.get("snippet") or ""
            rows.append(
                "<tr>"
                f"<td>{escape(str(j.get('company','')))}</td>"
                f"<td>{escape(str(j.get('title','')))}</td>"
                f"<td>{escape(str(j.get('location')))}</td>"
                f"<td>{escape(str(j.get('salary') or '未获取'))}</td>"
                f"<td>{escape(_preview(preview, 120))}</td>"
                f"<td>{source_inner}</td>"
                f"<td>{escape(str(j.get('fetched_at')))}</td>"
                "</tr>"
            )
        parts.append(
            "<table><tr><th>公司</th><th>岗位</th><th>地点</th><th>薪资</th>"
            f"<th>摘要（预览）</th><th>来源</th><th>抓取</th></tr>{''.join(rows)}</table>"
        )
        parts.append("<h2>岗位详情（完整 JD，点击展开）</h2>")
        for idx, j in enumerate(jds, 1):
            description = str(j.get("description") or "").strip()
            requirements = str(j.get("requirements") or "").strip()
            summary_bits = [
                str(bits) for bits in (
                    j.get("location"), j.get("salary") or "薪资未获取",
                    j.get("source"), j.get("fetched_at"),
                ) if str(bits or "").strip()
            ]
            link = (
                f'<a href="{escape(str(j.get("url")), quote=True)}">查看原始岗位页</a>'
                if j.get("url")
                else ""
            )
            body_parts = []
            if description:
                body_parts.append(
                    "<p><strong>岗位描述</strong>："
                    f"{_html_text(description)}</p>"
                )
            if requirements:
                body_parts.append(
                    "<p><strong>任职要求</strong>："
                    f"{_html_text(requirements)}</p>"
                )
            if not body_parts:
                body_parts.append('<p class="note">详情未获取——见「数据缺口」。</p>')
            parts.append(
                "<details class=\"jd\">"
                f"<summary><strong>{idx}. {escape(str(j.get('company','')))} · "
                f"{escape(str(j.get('title','')))}</strong>"
                f"<span class=\"compact\">　{'｜'.join(escape(bits) for bits in summary_bits)}</span>"
                "</summary>"
                + "".join(body_parts)
                + (f'<p class="compact">{link}</p>' if link else "")
                + "</details>"
            )
    else:
        parts.append('<p class="note">未获取到岗位样本（见「数据缺口」）——不猜测。</p>')

    parts.append(
        f"<h2>二、同背景经历（{len(cases)} 条）</h2>"
        + (""
           if cases
           else '<p class="note">未获取到同背景案例——不硬凑。</p>')
    )
    for c in cases:
        tag_bits = [str(x) for x in (c.get("education_tag"), c.get("year")) if x]
        tag = f"（{escape(' · '.join(tag_bits))}）" if tag_bits else ""
        hl = "；".join(str(h) for h in (c.get("highlights") or []))
        source_inner = (
            f'<a href="{escape(str(c.get("url", "")), quote=True)}">{escape(str(c.get("source") or "来源"))}</a>'
            if c.get("url")
            else escape(str(c.get("source") or ""))
        )
        salary = f"｜{escape(str(c['salary']))}" if c.get("salary") else ""
        hits = c.get("hit_terms") or []
        hits_html = (
            f'<span class="compact">｜命中：{escape("、".join(str(h) for h in hits))}</span>'
            if hits
            else ""
        )
        parts.append(
            f"<p>- <strong>{escape(str(c.get('title','')))}</strong>{tag}"
            f"｜{source_inner}{salary}{hits_html}"
            + (f'<span class="compact">｜{escape(str(c["date"]))}</span>' if c.get("date") else "")
            + (f'<br><span class="compact">要点：{escape(hl)}</span>' if hl else "")
            + "</p>"
        )

    parts.append("<h2>三、来源状态面板（失败也如实展示）</h2>")
    srows = []
    for s in report.get("source_status") or []:
        status = s.get("status")
        cls = "ok" if status == "ok" else ("fail" if status == "failed" else "")
        status_text = {"ok": "成功", "failed": "失败", "empty": "无结果"}.get(
            status, str(status or "")
        )
        note = escape(str(s.get("error") or "—"))
        if s.get("dropped_no_detail"):
            note += f"（剔除 {escape(str(s['dropped_no_detail']))} 条无详情岗位）"
        srows.append(
            "<tr>"
            f"<td>{escape(str(s.get('source','')))}</td>"
            f'<td><span class="pill {cls}">{escape(status_text)}</span></td>'
            f"<td>{escape(str(s.get('count',0)))}</td>"
            f"<td>{escape(str(s.get('elapsed',0)))}</td>"
            f"<td>{note}</td>"
            "</tr>"
        )
    parts.append(
        "<table><tr><th>来源</th><th>状态</th><th>条数</th><th>耗时(秒)</th>"
        f"<th>备注</th></tr>{''.join(srows)}</table>"
    )

    gaps = report.get("gaps") or []
    parts.append("<h2>四、数据缺口与建议</h2>")
    if gaps:
        gap_items = "".join(
            f"<li><strong>{escape(str(g.get('missing','')))}</strong>"
            f"（{escape(str(g.get('reason','')))}）——{escape(str(g.get('suggestion','')))}</li>"
            for g in gaps
        )
        parts.append(f"<ul>{gap_items}</ul>")
    else:
        parts.append("<p>本次调研没有明显缺口。</p>")

    parts.append(
        "<footer>本报告由抓取数据代码渲染生成，未使用 AI 记忆编造；"
        '原始数据在同名 .json。｜ <a href="index.html">← 返回资产中心</a></footer>'
    )
    return (
        '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
        "<title>Career Kit 市场调研报告</title>"
        f"<style>{_REPORT_CSS}</style></head><body><main>"
        + "".join(parts)
        + "</main></body></html>"
    )


def save_report(
    profile: Any,
    report: dict[str, Any],
    *,
    profile_name: str | None = None,
) -> dict[str, str]:
    """把报告三件套写入用户资产目录并刷新档案与 index，返回路径映射。

    profile.research 契约（供分析步引用，勿轻易变更字段名）：
    {generated_at, direction, report_md, report_html, report_json, index,
     jd_samples, cases, source_status, gaps, counts}
    """
    name = profile_name if profile_name is not None else get_active_profile_name()
    stem = next_asset_stem(
        report.get("direction") or report.get("context", {}).get("goal") or "调研",
        kind="research",
        profile_name=name,
    )
    md_text = render_markdown(report)
    html_text = render_html(report)
    json_text = json.dumps(report, ensure_ascii=False, indent=1)

    md_path = write_asset_text("research", name, f"{stem}.md", md_text, encoding="utf-8-sig")
    html_path = write_asset_text("research", name, f"{stem}.html", html_text)
    json_path = write_asset_text("research", name, f"{stem}.json", json_text)
    index_path = rebuild_index()

    payload = {
        "generated_at": report.get("generated_at"),
        "direction": report.get("direction"),
        "report_md": str(md_path),
        "report_html": str(html_path),
        "report_json": str(json_path),
        "index": str(index_path),
        "jd_samples": report.get("jd_samples") or [],
        "cases": report.get("cases") or [],
        "source_status": report.get("source_status") or [],
        "gaps": report.get("gaps") or [],
        "digest": report.get("digest") or {},
        "counts": report.get("counts") or {},
    }
    current = load_profile(name)
    current.research = payload
    current.touch()
    save_profile(current, name)
    if isinstance(profile, dict):
        profile.update(payload)
    else:
        profile.research = payload

    return {
        "md": str(md_path),
        "html": str(html_path),
        "json": str(json_path),
        "index": str(index_path),
    }
