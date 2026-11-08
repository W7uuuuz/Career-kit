"""市场调研报告——把批量抓取的真实数据渲染成用户可读的三件套并落盘。

纪律：报告正文 100% 代码渲染自抓取数据，不经 LLM 之手——「来源真实」的硬保证。
落盘位置走 assets.py（用户资产目录）：调研报告/<日期_方向>.{md,html,json}，
同时刷新档案的 research 字段与 index.html 资产中心。
"""

from __future__ import annotations

import json
from datetime import datetime
from html import escape
from pathlib import Path
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
    filtered_irrelevant = 0
    list_only_total = 0
    dropped_gaps: list[dict[str, str]] = []
    for family in gathered.get("jd_families") or []:
        rows = family.get("rows") or []
        status = family.get("status") or ("ok" if rows else "empty")
        if family.get("error"):
            status = "failed"
        dropped = int(family.get("dropped_no_detail") or 0)
        dropped_no_detail += dropped
        filtered = int(family.get("filtered_irrelevant") or 0)
        filtered_irrelevant += filtered
        list_only = int(family.get("list_only") or 0)
        list_only_total += list_only
        label = family.get("label") or family.get("slug") or "未知来源"
        source_status.append(
            {
                "source": label,
                "slug": str(family.get("slug") or ""),
                "scope": "jd",
                "status": status,
                "count": len(rows),
                "elapsed": round(float(family.get("elapsed") or 0), 1),
                "error": _one_line(family.get("error") or ""),
                "dropped_no_detail": dropped,
                "filtered_irrelevant": filtered,
                "list_only": list_only,
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
                    # 薪资来源说明：salary_source 记录实际返回薪资的数据源，
                    # salary_provenance 保留抓取器原始标记（如 BOSS 的 api/api_empty）。
                    # 只展示事实，不做估算或跨源补全。
                    "salary_source": (
                        _clip(row.get("source") or family.get("slug"), 20)
                        if str(row.get("salary") or "").strip()
                        else ""
                    ),
                    "salary_provenance": _clip(row.get("salary_source"), 20),
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

    # 案例源计数口径：用「最终进入花名册的条数」，与汇报和花名册保持一致
    # （原始抓取数只作补充说明，避免 5 条 vs 12 条的自相矛盾，P1-1）。
    kept_by_source: dict[str, int] = {}
    for case in cases:
        src = str(case.get("source") or "unknown")
        kept_by_source[src] = kept_by_source.get(src, 0) + 1
    for slug, raw_count in case_sources.items():
        raw = int(raw_count or 0)
        kept = kept_by_source.get(str(slug), 0)
        error = ""
        for warning in case_warnings:
            text = str(warning)
            if text.startswith(f"{slug}:"):
                error = _one_line(text.split(":", 1)[1].strip())
                break
        if slug == "local" and raw == 0 and kept == 0 and not error:
            continue  # 本地知识库为空是常态，不当作「来源无结果」计入缺口
        if error:
            status = "failed"
        elif kept > 0:
            status = "ok"
        else:
            status = "empty"
            if raw > 0:
                error = f"原始 {raw} 条未通过去重/相关度筛选"
        source_status.append(
            {
                "source": f"案例·{slug}",
                "slug": str(slug),
                "scope": "cases",
                "status": status,
                "count": kept,
                "raw_count": raw,
                "elapsed": 0.0,
                "error": error,
            }
        )

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
        "filtered_irrelevant": filtered_irrelevant,
        "list_only": list_only_total,
        "source_ok": sum(1 for s in source_status if s["status"] == "ok"),
        "source_fail": sum(1 for s in source_status if s["status"] == "failed"),
        "source_empty": sum(1 for s in source_status if s["status"] == "empty"),
    }

    salary = _build_salary_summary(jd_samples, source_status)

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
        "salary": salary,
    }


def _norm_title(text: Any) -> str:
    """标题归一化（去空白/大小写）——本地 JD 与本次 JD 去重用。"""
    return "".join(str(text or "").lower().split())


def _boss_status(source_status: list[dict[str, Any]]) -> str:
    """BOSS 在本次抓取中的状态：not_included / failed / ok / empty。"""
    entries = [
        s
        for s in source_status
        if "boss" in f"{s.get('source', '')} {s.get('slug', '')}".lower()
    ]
    if not entries:
        return "not_included"
    if any(e.get("status") == "failed" for e in entries):
        return "failed"
    if any(e.get("status") == "ok" for e in entries):
        return "ok"
    return "empty"


def _build_salary_summary(
    jd_samples: list[dict[str, Any]],
    source_status: list[dict[str, Any]],
) -> dict[str, Any]:
    """薪资覆盖事实：多少条含薪、来自哪些源、BOSS 是否参与。

    只统计抓取结果里真实返回的 salary 字段，不估算、不补全。
    """
    sources: list[str] = []
    with_salary = 0
    for sample in jd_samples:
        if not str(sample.get("salary") or "").strip():
            continue
        with_salary += 1
        label = str(
            sample.get("salary_source") or sample.get("source") or ""
        ).strip()
        if label and label not in sources:
            sources.append(label)
    boss = _boss_status(source_status)
    return {
        "sample_count": len(jd_samples),
        "with_salary": with_salary,
        "sources": sources,
        "boss_included": boss != "not_included",
        "boss_status": boss,
    }


_SALARY_CHANNEL_NOTE = (
    "当前可用含薪来源主要是 BOSS 直聘（列表明文薪资）；"
    "企业官网多数不公开薪资，仅少数岗位可能带薪资"
)
_SALARY_OPTIONS = (
    "可选动作：① 补充 BOSS 直聘（需先征得同意并扫码登录）后重跑；"
    "② 导入手头含薪 JD（import_jd / import_jd_file）；"
    "③ 接受本次薪资缺口，仅用岗位与要求做分析"
)


def _salary_gap(
    jd_samples: list[dict[str, Any]],
    source_status: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """薪资缺口：按真实覆盖情况说明原因，并给出可执行且真实存在的动作。"""
    if not jd_samples:
        return []
    summary = _build_salary_summary(jd_samples, source_status)
    total = int(summary["sample_count"])
    with_salary = int(summary["with_salary"])
    if with_salary >= total:
        return []
    if with_salary == 0:
        boss_status = summary["boss_status"]
        if boss_status == "failed":
            reason = "BOSS 直聘本次未成功（见来源状态面板），其余已抓来源不公开薪资"
        elif boss_status == "ok":
            reason = "BOSS 直聘本次未返回明文薪资，其余已抓来源不公开薪资"
        elif boss_status == "empty":
            reason = "BOSS 直聘本次无可用结果，其余已抓来源不公开薪资"
        else:
            reason = "本次未选择 BOSS 直聘，已抓企业官网多数不公开薪资"
        return [
            {
                "missing": f"全部 {total} 条岗位样本均无薪资数据",
                "reason": f"{reason}。{_SALARY_CHANNEL_NOTE}",
                "suggestion": _SALARY_OPTIONS,
            }
        ]
    sources = "、".join(summary["sources"]) or "未标注来源"
    return [
        {
            "missing": (
                f"仅 {with_salary}/{total} 条岗位含薪资（来源：{sources}）"
            ),
            "reason": (
                f"其余 {total - with_salary} 条来源未返回薪资字段；"
                f"{_SALARY_CHANNEL_NOTE}"
            ),
            "suggestion": _SALARY_OPTIONS,
        }
    ]


def _salary_render_line(info: dict[str, Any]) -> str:
    """报告展示用的薪资覆盖说明（事实陈述，不承诺未接入来源）。"""
    total = int(info.get("sample_count") or 0)
    if not total:
        return ""
    with_salary = int(info.get("with_salary") or 0)
    if not with_salary:
        return (
            f"薪资数据：0/{total} 条含明文薪资——原因与可选动作见「数据缺口」，"
            "不估算、不编造。"
        )
    sources = "、".join(str(s) for s in (info.get("sources") or []) if s)
    detail = f"{with_salary}/{total} 条含明文薪资"
    if sources:
        detail += f"（来源：{sources}）"
    return (
        f"薪资数据：{detail}。未含薪资仅表示该来源未返回薪资字段，"
        "不代表岗位无薪资。"
    )


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
        filtered = int(s.get("filtered_irrelevant") or 0)
        if filtered:
            gaps.append(
                {
                    "missing": f"来源「{s['source']}」有 {filtered} 条岗位因方向不匹配被过滤",
                    "reason": "搜索结果混入与本轮方向无关的岗位（如 AI-HR 培训生）",
                    "suggestion": "换更精确的关键词重跑，或放宽条件后人工筛选",
                }
            )
        list_only = int(s.get("list_only") or 0)
        if list_only:
            gaps.append(
                {
                    "missing": (
                        f"来源「{s['source']}」BOSS 仅列表数据，未抓 JD 详情"
                        f"（{list_only} 条）"
                    ),
                    "reason": "研究阶段 BOSS 默认 list-only，保留薪资与公司/地点/技能标签",
                    "suggestion": "需要 JD 全文时用 fetch_jd_detail(url) 交互式补抓单条",
                }
            )
    gaps.extend(_salary_gap(jd_samples, source_status))
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
        salary_line = _salary_render_line(report.get("salary") or {})
        if salary_line:
            lines.append(salary_line)
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
        if s.get("list_only"):
            note_bits.append(f"（{s['list_only']} 条仅列表数据，未抓 JD 详情）")
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
        salary_line = _salary_render_line(report.get("salary") or {})
        if salary_line:
            parts.append(f'<p class="compact">{escape(salary_line)}</p>')
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
        if s.get("list_only"):
            note += f"（{escape(str(s['list_only']))} 条仅列表数据，未抓 JD 详情）"
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
        '原始数据在同名 .json。｜ <a href="../../index.html">← 返回资产中心</a></footer>'
    )
    return (
        '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>Career Kit 市场调研报告</title>"
        f"<style>{_REPORT_CSS}</style></head><body><main>"
        + "".join(parts)
        + "</main></body></html>"
    )


def _sample_key(item: dict[str, Any]) -> tuple[str, ...]:
    url = str(item.get("url") or "").strip()
    if url:
        return ("url", url)
    return (
        "title",
        str(item.get("company") or ""),
        _norm_title(item.get("title")),
    )


def _dedupe_samples(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, ...]] = set()
    kept: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        key = _sample_key(item)
        if key in seen:
            continue
        seen.add(key)
        kept.append(item)
    return kept


def _merge_source_status(
    previous: list[dict[str, Any]], current: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """按 scope + slug/source 合并来源状态，避免分批抓取重复计数。"""
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for status in [*previous, *current]:
        if not isinstance(status, dict):
            continue
        scope = str(status.get("scope") or "jd")
        ident = str(status.get("slug") or status.get("source") or "")
        key = (scope, ident)
        old = merged.get(key)
        if old is None:
            merged[key] = dict(status)
            continue
        old_ok = old.get("status") == "ok"
        new_ok = status.get("status") == "ok"
        if old_ok and not new_ok:
            continue
        if old_ok and new_ok:
            combined = dict(status)
            for field in (
                "count", "raw_count", "dropped_no_detail", "filtered_irrelevant",
                "list_only",
            ):
                if field in old or field in status:
                    combined[field] = max(
                        int(old.get(field) or 0), int(status.get(field) or 0)
                    )
            merged[key] = combined
            continue
        merged[key] = dict(status)
    return list(merged.values())


def merge_reports(
    previous: dict[str, Any], current: dict[str, Any]
) -> dict[str, Any]:
    """同 fingerprint 的续抓结果合并成一份报告，避免同轮生成多份文件。"""
    jd_samples = _dedupe_samples(
        list(previous.get("jd_samples") or []) + list(current.get("jd_samples") or [])
    )
    cases = _dedupe_samples(
        list(previous.get("cases") or []) + list(current.get("cases") or [])
    )
    for idx, sample in enumerate(jd_samples, 1):
        sample["id"] = f"JD{idx:02d}"
    for idx, case in enumerate(cases, 1):
        case["id"] = f"CS{idx:02d}"

    source_status = _merge_source_status(
        list(previous.get("source_status") or []),
        list(current.get("source_status") or []),
    )
    # 不要把两批的数字直接相加：按合并后的来源状态重算，避免同一来源重复计数。
    dropped = sum(
        int(s.get("dropped_no_detail") or 0)
        for s in source_status
        if str(s.get("scope") or "jd") == "jd"
    )
    filtered_irrelevant = sum(
        int(s.get("filtered_irrelevant") or 0) for s in source_status
    )
    list_only = sum(int(s.get("list_only") or 0) for s in source_status)
    raw_cases = sum(
        int(s.get("raw_count") or 0)
        for s in source_status
        if str(s.get("scope") or "") == "cases"
    ) or len(cases)
    counts = {
        "jd_samples": len(jd_samples),
        "cases": len(cases),
        "cases_raw": raw_cases,
        "cases_filtered": max(0, raw_cases - len(cases)),
        "dropped_no_detail": dropped,
        "filtered_irrelevant": filtered_irrelevant,
        "list_only": list_only,
        "source_ok": sum(1 for s in source_status if s.get("status") == "ok"),
        "source_fail": sum(1 for s in source_status if s.get("status") == "failed"),
        "source_empty": sum(1 for s in source_status if s.get("status") == "empty"),
    }
    warnings = list(
        dict.fromkeys(
            [
                *(previous.get("case_warnings") or []),
                *(current.get("case_warnings") or []),
            ]
        )
    )
    merged = {
        **current,
        "generated_at": current.get("generated_at"),
        "jd_samples": jd_samples,
        "cases": cases,
        "source_status": source_status,
        "case_warnings": warnings[:10],
        "gaps": _derive_gaps(jd_samples, cases, source_status),
        "digest": build_digest(
            jd_samples, cases, dropped, raw_case_count=raw_cases
        ),
        "counts": counts,
        "salary": _build_salary_summary(jd_samples, source_status),
    }
    merged["fingerprint"] = current.get("fingerprint") or previous.get("fingerprint") or ""
    merged["round_key"] = current.get("round_key") or previous.get("round_key") or ""
    return merged


def _read_report_json(path: str) -> dict[str, Any]:
    if not path:
        return {}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _recent_report(previous: dict[str, Any], max_age_seconds: int = 7200) -> bool:
    path = str(previous.get("report_json") or "")
    try:
        saved = datetime.strptime(
            str(previous.get("generated_at") or ""), "%Y-%m-%d %H:%M"
        )
        age = (datetime.now() - saved).total_seconds()
    except (TypeError, ValueError):
        try:
            age = datetime.now().timestamp() - Path(path).stat().st_mtime
        except OSError:
            return False
    return 0 <= age <= max_age_seconds


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
    current_profile = load_profile(name)
    previous = current_profile.research or {}
    fingerprint = str(report.get("fingerprint") or "")
    round_key = str(report.get("round_key") or "")
    previous_fingerprint = str(previous.get("fingerprint") or "")
    previous_round_key = str(previous.get("round_key") or "")
    # 同一轮判定：双方都有 round_key 时优先比 round_key（分批 specs 不同也能合并）；
    # 否则回退 fingerprint。两种判定都受 2 小时窗口约束。
    if round_key and previous_round_key:
        same_round = round_key == previous_round_key
    else:
        same_round = bool(fingerprint and fingerprint == previous_fingerprint)
    reuse_stem = ""
    if same_round and _recent_report(previous):
        previous_report = _read_report_json(str(previous.get("report_json") or ""))
        if previous_report:
            report = merge_reports(previous_report, report)
            reuse_stem = Path(str(previous["report_json"])).stem
            report["fingerprint"] = fingerprint or previous_fingerprint
            report["round_key"] = round_key or previous_round_key

    stem = reuse_stem or next_asset_stem(
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
        "fingerprint": report.get("fingerprint") or "",
        "round_key": report.get("round_key") or "",
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
