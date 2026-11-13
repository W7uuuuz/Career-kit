"""市场调研报告——把批量抓取的真实数据渲染成用户可读的报告并落盘。

纪律：报告正文 100% 代码渲染自抓取数据，不经 LLM 之手——「来源真实」的硬保证。
落盘位置走 assets.py（用户资产目录）：调研报告/<日期_方向>.{md,json}，
同时刷新档案的 research 字段。
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from .assets import next_asset_stem, write_asset_text
from .core.domain.labels import reason_label
from .research_digest import build_digest, parse_salary
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


# 源维度：一个来源只能有一个最终状态（ok > failed > empty）。
# 任一路径失败都按失败计，避免「失败」被「无结果」掩盖；source_status 仍保留
# 逐 scope 明细供复核，汇总/播报统一走最终状态，避免同一源被重复计数。
_SOURCE_RANK = {"ok": 3, "failed": 2, "empty": 1, "skipped": 0}


def _source_final_states(
    source_status: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for item in source_status:
        if not isinstance(item, dict):
            continue
        key = str(item.get("slug") or item.get("source") or "").strip()
        if not key:
            continue
        entry = merged.get(key)
        if entry is None:
            entry = {
                "source": str(item.get("source") or key),
                "slug": key,
                "status": str(item.get("status") or "empty"),
                "scopes": [],
                "count": 0,
                "attempts": 0,
                "retried": False,
                "errors": [],
            }
            merged[key] = entry
        status = str(item.get("status") or "empty")
        if _SOURCE_RANK.get(status, 0) > _SOURCE_RANK.get(entry["status"], 0):
            entry["status"] = status
        scope = str(item.get("scope") or "jd")
        if scope not in entry["scopes"]:
            entry["scopes"].append(scope)
        entry["count"] = int(entry["count"]) + int(item.get("count") or 0)
        entry["attempts"] = max(
            int(entry["attempts"] or 0), int(item.get("attempts") or 0)
        )
        entry["retried"] = bool(entry["retried"] or item.get("retried"))
        error = _one_line(item.get("error") or "")
        if error and error not in entry["errors"]:
            entry["errors"].append(error)
        if not str(item.get("source") or "").startswith("案例·"):
            entry["source"] = str(item.get("source") or entry["source"])
    states = list(merged.values())
    for state in states:
        state["error"] = "；".join(state.pop("errors"))
    return states


def _is_jd_item(item: dict[str, Any]) -> bool:
    """判断案例列表里的一条实际是 JD（企业要求）还是面经/经验帖。"""
    category = str(item.get("category") or "")
    if category == "jd":
        return True
    if category == "case":
        return False
    if str(item.get("origin") or "") == "local_jd":
        return True
    source = str(item.get("source") or "").lower()
    if source in {"github", "nowcoder", "local", ""}:
        return False
    return str(item.get("kind") or "") == "interview_requirements"


def _case_source_key(case: dict[str, Any], known: set[str]) -> str:
    """案例归属源：本地知识库命中（有 local_path）归 local，其余按卡片来源。"""
    source = str(case.get("source") or "unknown")
    if source in known:
        return source
    if case.get("local_path") or case.get("origin") == "local":
        return "local"
    return source


_GRAD_YEAR_RANGE = re.compile(r"(20\d{2})\s*[-/／、~至]\s*(20\d{2})")
_GRAD_YEAR = re.compile(r"(20\d{2})\s*届")
_EDU_MIN_PATTERNS = (
    re.compile(r"(博士|硕士|本科|大专|专科)(?:学历)?(?:及以上|以上|或以上|起)"),
    re.compile(r"学历(?:要求)?[：:]\s*(博士|硕士|本科|大专|专科)"),
)
_WEEKLY_DAYS_PATTERNS = (
    re.compile(r"每周(?:到岗|出勤|实习|工作)?\s*(\d)\s*(?:[-~至]\s*\d\s*)?天"),
    re.compile(r"(?:一周|每星期)\s*(\d)\s*天"),
    re.compile(r"(\d)\s*天\s*/\s*周"),
    re.compile(r"至少\s*(\d)\s*天"),
)
_DURATION_PATTERNS = (
    re.compile(r"实习(?:期|时间)?\s*(\d+)\s*[-~至]\s*(\d+)\s*个月"),
    re.compile(r"实习(?:期|时间)?\s*(\d+)\s*个月"),
    re.compile(r"至少\s*(\d+)\s*个月"),
    re.compile(r"(\d+)\s*个月(?:以上|起)"),
)


def _positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _extract_graduation_years(text: str) -> list[int]:
    years: set[int] = set()
    for match in _GRAD_YEAR_RANGE.finditer(text):
        start, end = int(match.group(1)), int(match.group(2))
        if 0 <= end - start <= 4:
            years.update(range(start, end + 1))
    for match in _GRAD_YEAR.finditer(text):
        years.add(int(match.group(1)))
    return sorted(years)


def _extract_education_min(text: str) -> str:
    for pattern in _EDU_MIN_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1)
    return ""


def _extract_weekly_days(text: str) -> int | None:
    for pattern in _WEEKLY_DAYS_PATTERNS:
        match = pattern.search(text)
        if match:
            days = _positive_int(match.group(1))
            if days and days <= 7:
                return days
    return None


def _extract_duration_months(text: str) -> int | None:
    for pattern in _DURATION_PATTERNS:
        match = pattern.search(text)
        if match:
            months = _positive_int(match.group(1))
            if months and months <= 24:
                return months
    return None


def _hard_fields(row: dict[str, Any]) -> dict[str, Any]:
    """结构化硬门槛字段；抽不到留空，不猜测。"""
    text = " ".join(
        str(row.get(key) or "")
        for key in ("title", "summary", "description", "requirements")
    )
    degree = str(row.get("degree") or row.get("education") or "").strip()
    if degree in {"博士", "硕士", "本科", "大专", "专科"}:
        education_min = degree
    else:
        education_min = _extract_education_min(degree) or _extract_education_min(text)
    if not degree and education_min:
        degree = education_min
    return {
        "degree": degree,
        "education_min": education_min,
        "graduation_years": _extract_graduation_years(text),
        "weekly_days": _positive_int(row.get("weekly_days"))
        or _extract_weekly_days(text),
        "duration_months": _positive_int(row.get("duration_months"))
        or _extract_duration_months(text),
        "chance": str(row.get("chance") or "").strip(),
    }


def _concentration_info(
    jd_samples: list[dict[str, Any]],
    source_status: list[dict[str, Any]],
) -> dict[str, Any]:
    total = len(jd_samples)
    if not total:
        return {}
    counts = Counter(
        str(sample.get("source") or "unknown") for sample in jd_samples
    )
    top_source, top_count = counts.most_common(1)[0]
    share = round(top_count / total, 2)
    distinct = len(counts)
    if distinct == 1:
        risk = "high"
    elif share >= 0.6:
        risk = "medium"
    else:
        risk = "low"
    states = _source_final_states(source_status)
    failed = [s["source"] for s in states if s.get("status") == "failed"]
    used = {str(s.get("slug") or "") for s in states}
    used.add(top_source)
    alternatives = _registered_alternatives(used) if risk != "low" else []
    return {
        "sample_count": total,
        "distinct_sources": distinct,
        "top_source": top_source,
        "top_count": top_count,
        "top_share": share,
        "risk": risk,
        "failed_sources": failed,
        "alternatives": alternatives,
    }


def _registered_alternatives(used: set[str]) -> list[str]:
    """从已注册源里给出替代候选，不虚构来源。"""
    try:
        from .scrapers.loader import list_scrapers

        names = [
            str(item.get("name") or item.get("id") or "")
            for item in list_scrapers()
            if str(item.get("id") or "") not in used
            and str(item.get("id") or "") not in {"boss", "nowcoder", "github"}
            and "keyword" in (item.get("params") or {})
        ]
    except Exception:  # noqa: BLE001 - 注册表异常时不给候选，不编造
        return []
    return [name for name in names if name][:3]


def _concentration_gap(
    jd_samples: list[dict[str, Any]],
    source_status: list[dict[str, Any]],
) -> list[dict[str, str]]:
    info = _concentration_info(jd_samples, source_status)
    if not info or info.get("risk") == "low":
        return []
    top_source = info["top_source"]
    top_count = int(info.get("top_count") or 0)
    risk_text = "高" if info["risk"] == "high" else "偏高"
    risk_label = "单一来源集中度" if info["risk"] == "high" else "来源集中度"
    reason = (
        f"{info['distinct_sources']} 个来源返回了岗位样本，"
        "单一来源偏差会影响需求分析与硬筛结论"
    )
    action_bits = []
    if info["failed_sources"]:
        action_bits.append("重试失败源：" + "、".join(info["failed_sources"]))
    if info["alternatives"]:
        action_bits.append("补充已注册官方源：" + "、".join(info["alternatives"]))
    action_bits.append("或用 import_jd 导入手头 JD 交叉验证")
    return [
        {
            "missing": (
                f"岗位样本{risk_label}风险{risk_text}："
                f"{top_count}/{info['sample_count']} 条来自「{top_source}」"
            ),
            "reason": reason,
            "suggestion": "；".join(action_bits),
        }
    ]


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
        "graduation_year": str(
            who.get("graduation_year") or want.get("graduation_year") or ""
        ),
        "job_kind": str(gathered.get("job_kind") or want.get("job_kind") or ""),
        "resume_trust": _clip(
            (have.get("self_assessment") or {}).get("resume_trust", ""), 20
        ),
    }

    jd_samples: list[dict[str, Any]] = []
    source_status: list[dict[str, Any]] = []
    dropped_no_detail = 0
    filtered_irrelevant = 0
    list_only_total = 0
    screened_out_total: dict[str, int] = {}
    dropped_gaps: list[dict[str, str]] = []
    for family in gathered.get("jd_families") or []:
        rows = family.get("rows") or []
        status = family.get("status") or ("ok" if rows else "empty")
        if family.get("error") and status != "skipped":
            status = "failed"
        dropped = int(family.get("dropped_no_detail") or 0)
        dropped_no_detail += dropped
        filtered = int(family.get("filtered_irrelevant") or 0)
        filtered_irrelevant += filtered
        list_only = int(family.get("list_only") or 0)
        list_only_total += list_only
        screened_out = {
            str(reason): int(count)
            for reason, count in (family.get("screened_out") or {}).items()
            if int(count or 0)
        }
        for reason, count in screened_out.items():
            screened_out_total[reason] = screened_out_total.get(reason, 0) + count
        label = family.get("label") or family.get("slug") or "未知来源"
        filtered_samples = [
            item for item in (family.get("filtered_samples") or [])
            if isinstance(item, dict)
        ]
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
                "screened_out": screened_out,
                "filtered_titles": [
                    str(item.get("title") or "") for item in filtered_samples
                ][:10],
                "filtered_samples": filtered_samples[:10],
                "list_only": list_only,
                "attempts": int(family.get("attempts") or 1),
                "retried": bool(family.get("retried")),
                "from_cache": bool(family.get("from_cache")),
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
            hard = _hard_fields(row)
            jd_samples.append(
                {
                    "company": _clip(row.get("company") or label, 40),
                    "title": _clip(row.get("title"), 120),
                    "location": _clip(row.get("location"), 60),
                    "salary": _clip(row.get("salary"), 40),
                    "degree": hard["degree"],
                    "education_min": hard["education_min"],
                    "graduation_years": hard["graduation_years"],
                    "weekly_days": hard["weekly_days"],
                    "duration_months": hard["duration_months"],
                    "chance": hard["chance"],
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

    raw_cases = [
        case for case in (cases_result.get("cases") or [])
        if isinstance(case, dict) and not case.get("error")
    ]
    raw_case_items = [case for case in raw_cases if not _is_jd_item(case)]
    jd_from_cases = len(raw_cases) - len(raw_case_items)
    cases: list[dict[str, Any]] = []
    for case in raw_case_items:
        bg = case.get("background") or {}
        case_url = str(case.get("url") or "").strip()
        case_title = _clip(case.get("title"), 120)
        if case_url and case_url in jd_urls:
            continue
        if not case_url and _norm_title(case_title) in jd_titles:
            continue
        content = str(case.get("content") or "").strip()
        cases.append(
            {
                "kind": _clip(case.get("kind"), 30),
                "category": "case",
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
                "content": content,
                "content_status": (
                    str(case.get("content_status") or "")
                    or ("ok" if content else "unavailable")
                ),
                "content_error": _one_line(case.get("content_error") or ""),
                "date": _clip(case.get("date"), 20),
                "match_score": case.get("match_score"),
            }
        )

    for idx, case in enumerate(cases, 1):
        case["id"] = f"CS{idx:02d}"

    # 案例源计数口径：只统计实际案例（category=case），本地 JD/企业要求不计入案例数。
    known_case_sources = {str(slug) for slug in case_sources}
    kept_by_source: dict[str, int] = {}
    for case in cases:
        src = _case_source_key(case, known_case_sources)
        kept_by_source[src] = kept_by_source.get(src, 0) + 1
    raw_by_source = Counter(
        _case_source_key(case, known_case_sources) for case in raw_case_items
    )
    for slug, _raw_count in case_sources.items():
        raw = int(raw_by_source.get(str(slug), 0))
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

    if cases_result.get("skipped_reason") and not any(
        str(s.get("scope") or "") == "cases" for s in source_status
    ):
        source_status.append(
            {
                "source": "案例",
                "slug": "cases",
                "scope": "cases",
                "status": "skipped",
                "count": 0,
                "raw_count": 0,
                "elapsed": 0.0,
                "error": _one_line(str(cases_result.get("skipped_reason") or "")),
            }
        )

    source_states = _source_final_states(source_status)
    digest = build_digest(
        jd_samples, cases, dropped_no_detail, raw_case_count=len(raw_case_items)
    )

    gaps = _derive_gaps(jd_samples, cases, source_status)
    gaps = dropped_gaps + gaps

    counts = {
        "jd_samples": len(jd_samples),
        "cases": len(cases),
        "cases_raw": len(raw_case_items),
        "cases_filtered": max(0, len(raw_case_items) - len(cases)),
        "jd_from_cases": jd_from_cases,
        "dropped_no_detail": dropped_no_detail,
        "filtered_irrelevant": filtered_irrelevant,
        "screened_out": dict(screened_out_total),
        "screened_total": sum(screened_out_total.values()),
        "list_only": list_only_total,
        "source_ok": sum(1 for s in source_states if s["status"] == "ok"),
        "source_fail": sum(1 for s in source_states if s["status"] == "failed"),
        "source_empty": sum(1 for s in source_states if s["status"] == "empty"),
        "source_skip": sum(1 for s in source_states if s["status"] == "skipped"),
    }

    salary = _build_salary_summary(jd_samples, source_status)
    concentration = _concentration_info(jd_samples, source_status)

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
        "source_states": source_states,
        "source_concentration": concentration,
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
    jd_entries = [s for s in entries if str(s.get("scope") or "jd") == "jd"]
    states = _source_final_states(jd_entries or entries)
    if any(state.get("status") == "ok" for state in states):
        return "ok"
    if any(state.get("status") == "failed" for state in states):
        return "failed"
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
    by_type: Counter[str] = Counter()
    for sample in jd_samples:
        parsed = parse_salary(sample.get("salary"))
        if not parsed:
            continue
        with_salary += 1
        by_type[str(parsed["type"])] += 1
        label = str(
            sample.get("salary_source") or sample.get("source") or ""
        ).strip()
        if label and label not in sources:
            sources.append(label)
    boss = _boss_status(source_status)
    return {
        "sample_count": len(jd_samples),
        "with_salary": with_salary,
        "monthly_count": by_type.get("monthly", 0),
        "daily_count": by_type.get("daily", 0),
        "annual_count": by_type.get("annual", 0),
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
    type_bits = "、".join(
        f"{label} {info.get(key)} 条"
        for key, label in (
            ("monthly_count", "月薪"), ("daily_count", "日薪"),
            ("annual_count", "年薪"),
        )
        if info.get(key)
    )
    if type_bits:
        detail += f"（{type_bits}）"
    if sources:
        detail += f"（来源：{sources}）"
    return (
        f"薪资数据：{detail}。日薪/月薪/年薪按原文分别统计，未做跨口径换算；"
        "未含薪资仅表示该来源未返回薪资字段，不代表岗位无薪资。"
    )


def _derive_gaps(
    jd_samples: list[dict[str, Any]],
    cases: list[dict[str, Any]],
    source_status: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """自动生成数据缺口清单——不猜测，只陈述没拿到什么与建议补偿方式。"""
    gaps: list[dict[str, str]] = []
    # 源维度：一个源只报一次最终状态，避免同一源同时出现在「失败」与「无结果」。
    for s in _source_final_states(source_status):
        scope_label = "案例来源" if "cases" in (s.get("scopes") or []) else "来源"
        if s["status"] == "failed":
            gaps.append(
                {
                    "missing": f"{scope_label}「{s['source']}」本次未获取到数据",
                    "reason": _one_line(s.get("error")) or "抓取失败",
                    "suggestion": "见来源状态面板；必要时提供手头 JD 用 import_jd 补充",
                }
            )
        elif s["status"] == "empty":
            gaps.append(
                {
                    "missing": f"{scope_label}「{s['source']}」未搜到匹配内容",
                    "reason": "查询词与该源无匹配，或详情均不可用",
                    "suggestion": "换关键词重跑，或补充手头 JD",
                }
            )
        elif s["status"] == "skipped":
            gaps.append(
                {
                    "missing": (
                        f"{scope_label}「{s['source']}」本轮未采集（超时/预算/异常）"
                        if "cases" in (s.get("scopes") or [])
                        else f"{scope_label}「{s['source']}」不服务目标招聘类型，已跳过"
                    ),
                    "reason": _one_line(s.get("error")) or "该源没有对应通道",
                    "suggestion": "这不是抓取失败；换用支持该通道的来源即可",
                }
            )
    # 条目维度：同一原因跨来源合并成一条，避免缺口列表被重复项占满。
    filtered = sum(int(s.get("filtered_irrelevant") or 0) for s in source_status)
    if filtered:
        samples = [
            item
            for s in source_status
            for item in (s.get("filtered_samples") or [])
            if isinstance(item, dict)
        ]
        titles = [
            str(item.get("title") or "").strip()
            for item in samples
            if str(item.get("title") or "").strip()
        ]
        gaps.append(
            {
                "missing": f"有 {filtered} 条岗位因方向不匹配被过滤",
                "reason": "搜索结果混入与本轮方向无关的岗位（如 AI-HR 培训生）",
                "suggestion": (
                    "被过滤示例：" + "、".join(titles[:5]) + "；"
                    if titles
                    else ""
                ) + "换更精确的关键词重跑，或放宽条件后人工复核",
            }
        )

    screened: dict[str, int] = {}
    for s in source_status:
        for reason, count in (s.get("screened_out") or {}).items():
            if str(reason) in {"direction_mismatch", "direction_excluded"}:
                continue
            screened[str(reason)] = screened.get(str(reason), 0) + int(count or 0)
    if screened:
        total = sum(screened.values())
        parts = "、".join(
            f"{reason_label(reason)} {count} 条"
            for reason, count in sorted(screened.items(), key=lambda item: -item[1])
        )
        gaps.append(
            {
                "missing": f"有 {total} 条岗位因资格不符被剔除（{parts}）",
                "reason": "岗位明确不接受你的届别/学历/招聘类型，或命中你设置的排除方向",
                "suggestion": "若目标届别尚未开放，先投当前开放的日常实习；也可放宽排除条件复核",
            }
        )

    list_only = sum(int(s.get("list_only") or 0) for s in source_status)
    if list_only:
        gaps.append(
            {
                "missing": f"BOSS 仅列表数据，未抓 JD 详情（{list_only} 条）",
                "reason": "研究阶段 BOSS 默认 list-only，保留薪资与公司/地点/技能标签",
                "suggestion": "需要 JD 全文时用 fetch_jd_detail(url) 交互式补抓单条",
            }
        )
    gaps.extend(_salary_gap(jd_samples, source_status))
    gaps.extend(_concentration_gap(jd_samples, source_status))
    if not cases:
        case_entries = [
            s for s in source_status if str(s.get("scope") or "") == "cases"
        ]
        if not case_entries:
            gaps.append(
                {
                    "missing": "本轮未请求案例",
                    "reason": "case_query 为空，未查询案例源",
                    "suggestion": "需要同背景经历时，带 case_query.role 再跑一次",
                }
            )
        elif all(s.get("status") == "empty" for s in case_entries):
            gaps.append(
                {
                    "missing": "未搜到同背景成功经历案例",
                    "reason": "案例源已查询，但本次无匹配（或查询过于具体）",
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
    states = report.get("source_states") or _source_final_states(
        report.get("source_status") or []
    )
    state_counts = Counter(str(s.get("status") or "empty") for s in states)
    lines.append(
        "来源维度（每源只计一个最终状态）："
        f"成功 {state_counts.get('ok', 0)} · 失败 {state_counts.get('failed', 0)} · "
        f"无结果 {state_counts.get('empty', 0)}；"
        f"条目维度：过滤 {counts.get('filtered_irrelevant', 0)} 条、"
        f"剔除无详情 {counts.get('dropped_no_detail', 0)} 条。"
    )
    lines.append("")
    lines.append("| 来源 | 状态 | 条数 | 耗时(秒) | 备注 |")
    lines.append("|---|---|---|---|---|")
    for s in report.get("source_status") or []:
        status_text = {"ok": "成功", "failed": "失败", "empty": "无结果"}.get(
            s.get("status"), s.get("status", "")
        )
        note_bits = [_md_escape_md(s.get("error", "") or "—")]
        if s.get("attempts", 1) > 1:
            note_bits.append(f"（重试后成功/结束，共 {s['attempts']} 次）")
        if s.get("dropped_no_detail"):
            note_bits.append(f"（剔除 {s['dropped_no_detail']} 条无详情岗位）")
        if s.get("filtered_irrelevant"):
            note_bits.append(f"（过滤 {s['filtered_irrelevant']} 条方向不匹配）")
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
    if counts.get("jd_from_cases"):
        counts_text += f"；另有 {counts['jd_from_cases']} 条本地 JD 归入企业要求，未计案例"
    lines.append(
        f"---\n样本统计：{counts_text}。原始数据在同名 .json；本报告及全部来源"
        "可在桌面「Career Kit」快捷方式打开的控制台中查看。"
        "本报告由抓取数据代码渲染生成，未使用 AI 记忆编造。"
    )
    return "\n".join(lines)


def _md_escape_md(text: str) -> str:
    return str(text).replace("|", "\\|") if text else ""


def _md_block(text: str) -> str:
    """多行正文 → markdown 硬换行块（保留完整内容，不裁剪）。"""
    lines = [line.rstrip() for line in str(text).strip().splitlines() if line.strip()]
    return "  \n".join(lines)


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


def _merge_filtered_traces(
    first: Any, second: Any
) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    merged: list[dict[str, str]] = []
    for item in [*(first or []), *(second or [])]:
        if not isinstance(item, dict):
            continue
        key = (str(item.get("title") or ""), str(item.get("reason") or ""))
        if key in seen:
            continue
        seen.add(key)
        merged.append(dict(item))
    return merged


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
        combined = dict(status)
        for field in (
            "count", "raw_count", "dropped_no_detail", "filtered_irrelevant",
            "list_only",
        ):
            if field in old or field in status:
                combined[field] = max(
                    int(old.get(field) or 0), int(status.get(field) or 0)
                )
        combined["filtered_samples"] = _merge_filtered_traces(
            old.get("filtered_samples"), status.get("filtered_samples")
        )
        old_screened = old.get("screened_out") or {}
        new_screened = status.get("screened_out") or {}
        combined["screened_out"] = {
            reason: max(
                int(old_screened.get(reason) or 0),
                int(new_screened.get(reason) or 0),
            )
            for reason in {*old_screened, *new_screened}
        }
        combined["filtered_titles"] = [
            str(item.get("title") or "")
            for item in combined["filtered_samples"]
        ]
        combined["attempts"] = max(
            int(old.get("attempts") or 1), int(status.get("attempts") or 1)
        )
        combined["retried"] = bool(old.get("retried") or status.get("retried"))
        merged[key] = combined
    return list(merged.values())


def merge_reports(
    previous: dict[str, Any], current: dict[str, Any]
) -> dict[str, Any]:
    """同 fingerprint 的续抓结果合并成一份报告，避免同轮生成多份文件。"""
    jd_samples = _dedupe_samples(
        list(previous.get("jd_samples") or []) + list(current.get("jd_samples") or [])
    )
    all_cases = _dedupe_samples(
        list(previous.get("cases") or []) + list(current.get("cases") or [])
    )
    cases = [case for case in all_cases if not _is_jd_item(case)]
    jd_from_merged_cases = len(all_cases) - len(cases)
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
    screened_out: dict[str, int] = {}
    for s in source_status:
        for reason, count in (s.get("screened_out") or {}).items():
            screened_out[str(reason)] = screened_out.get(str(reason), 0) + int(
                count or 0
            )
    raw_cases = sum(
        int(s.get("raw_count") or 0)
        for s in source_status
        if str(s.get("scope") or "") == "cases"
    ) or len(cases)
    source_states = _source_final_states(source_status)
    counts = {
        "jd_samples": len(jd_samples),
        "cases": len(cases),
        "cases_raw": raw_cases,
        "cases_filtered": max(0, raw_cases - len(cases)),
        "jd_from_cases": max(
            jd_from_merged_cases,
            int((previous.get("counts") or {}).get("jd_from_cases") or 0)
            + int((current.get("counts") or {}).get("jd_from_cases") or 0),
        ),
        "dropped_no_detail": dropped,
        "filtered_irrelevant": filtered_irrelevant,
        "screened_out": screened_out,
        "screened_total": sum(screened_out.values()),
        "list_only": list_only,
        "source_ok": sum(1 for s in source_states if s.get("status") == "ok"),
        "source_fail": sum(1 for s in source_states if s.get("status") == "failed"),
        "source_empty": sum(1 for s in source_states if s.get("status") == "empty"),
        "source_skip": sum(1 for s in source_states if s.get("status") == "skipped"),
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
        "source_states": source_states,
        "source_concentration": _concentration_info(jd_samples, source_status),
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
    """把报告写入用户资产目录并刷新档案，返回路径映射。

    profile.research 契约（供分析步引用，勿轻易变更字段名）：
    {generated_at, direction, report_md, report_json,
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
    json_text = json.dumps(report, ensure_ascii=False, indent=1)

    md_path = write_asset_text("research", name, f"{stem}.md", md_text, encoding="utf-8-sig")
    json_path = write_asset_text("research", name, f"{stem}.json", json_text)
    for written in (md_path, json_path):
        if not written.exists():
            raise OSError(f"报告写入失败，文件不存在：{written}")

    payload = {
        "generated_at": report.get("generated_at"),
        "direction": report.get("direction"),
        "fingerprint": report.get("fingerprint") or "",
        "round_key": report.get("round_key") or "",
        "report_md": str(md_path),
        "report_json": str(json_path),
        "jd_samples": report.get("jd_samples") or [],
        "cases": report.get("cases") or [],
        "source_status": report.get("source_status") or [],
        "source_states": report.get("source_states") or [],
        "source_concentration": report.get("source_concentration") or {},
        "gaps": report.get("gaps") or [],
        "digest": report.get("digest") or {},
        "counts": report.get("counts") or {},
        "salary": report.get("salary") or {},
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
        "json": str(json_path),
    }

