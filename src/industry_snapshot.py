"""行业快照——用通用数据源生成轻量认知卡，不依赖行业定制爬虫。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .industries.loader import match_major
from .paths import DATA_ROOT
from .research_digest import build_digest


def _boss_logged_in() -> bool:
    """隔离登录检查，便于测试与后续替换通用源。"""
    try:
        from .scrapers.boss.auth import has_valid_cookies

        return has_valid_cookies()
    except Exception:
        return False


def _salary_stats(samples: list[dict[str, Any]]) -> dict[str, Any]:
    if not samples:
        return {"count": 0}
    return build_digest(samples, [], raw_case_count=0).get("salary") or {"count": 0}


def _collect_market(
    pack: dict[str, Any],
    city: str,
    limit: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    """用通用招聘源抓当前在招样本；未登录/失败只记缺口，不阻断快照。"""
    warnings: list[str] = []
    if not _boss_logged_in():
        return [], ["BOSS 直聘未登录或登录态已过期：本次未获取实时招聘薪资；重新登录后可重试。"]

    from .scrapers import search_company_jobs

    roles = [r for r in (pack.get("roles") or []) if isinstance(r, dict)]
    if not roles:
        return [], ["行业配置缺少岗位族，无法搜索招聘样本。"]
    market_roles = roles[:5]
    per_role = max(2, min(5, limit // len(market_roles)))
    jobs: list[dict[str, Any]] = []
    for role in market_roles:
        keywords = [str(k).strip() for k in (role.get("keywords") or []) if str(k).strip()]
        keyword = keywords[0] if keywords else str(role.get("name") or "").strip()
        if not keyword:
            continue
        try:
            result = search_company_jobs(
                "boss",
                keyword=keyword,
                city=city or "全国",
                limit=per_role,
            )
        except Exception as exc:  # noqa: BLE001 — 单源失败不阻断
            warnings.append(f"BOSS/{role.get('name', keyword)}：{exc}")
            continue
        if result.get("error"):
            warnings.append(f"BOSS/{role.get('name', keyword)}：{result['error']}")
            continue
        for item in result.get("results") or []:
            if not isinstance(item, dict) or item.get("error"):
                continue
            row = dict(item)
            row["_role_id"] = role.get("id", "")
            row["_role_name"] = role.get("name", "")
            jobs.append(row)
    return jobs, warnings


def _load_outcomes(industry_id: str) -> dict[str, Any] | None:
    """可选的同行业/相关专业去向数据；接入前如实留空。"""
    path = DATA_ROOT / "industry_outcomes" / f"{industry_id}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _role_market(pack: dict[str, Any], jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    roles = [r for r in (pack.get("roles") or []) if isinstance(r, dict)]
    result: list[dict[str, Any]] = []
    for role in roles:
        rid = role.get("id", "")
        samples = [j for j in jobs if j.get("_role_id") == rid]
        salary = _salary_stats(samples)
        titles = []
        urls = []
        for item in samples[:3]:
            title = str(item.get("title") or "").strip()
            if title and title not in titles:
                titles.append(title)
            url = str(item.get("url") or "").strip()
            if url and url not in urls:
                urls.append(url)
        result.append(
            {
                "id": rid,
                "name": role.get("name", ""),
                "summary": role.get("summary", ""),
                "day_to_day": role.get("day_to_day") or [],
                "entry": role.get("entry", ""),
                "skills": role.get("skills") or [],
                "growth": role.get("growth", ""),
                "fit_signals": role.get("fit_signals") or [],
                "dealbreakers": role.get("dealbreakers") or [],
                "market": {
                    "sample_count": len(samples),
                    "salary": salary,
                    "sample_titles": titles,
                    "sample_urls": urls,
                },
            }
        )
    return result


def _source_entries(pack: dict[str, Any], job_count: int, warnings: list[str]) -> list[dict[str, Any]]:
    sources = [
        {
            "name": "BOSS直聘",
            "type": "job_market",
            "status": "ok" if job_count else "unavailable",
            "note": (
                f"当前在招样本 {job_count} 条；薪资为招聘区间，不是毕业生实际薪资。"
                if job_count
                else "未获取实时招聘样本。"
            ),
        }
    ]
    for benchmark in pack.get("benchmarks") or []:
        if not isinstance(benchmark, dict):
            continue
        sources.append(
            {
                "name": benchmark.get("source", ""),
                "type": "benchmark",
                "status": "ok",
                "url": benchmark.get("url", ""),
                "note": benchmark.get("note", ""),
            }
        )
    for warning in warnings:
        sources.append({"name": "BOSS直聘", "type": "job_market", "status": "warning", "note": warning})
    return sources


def build_snapshot(
    pack: dict[str, Any],
    *,
    major: str = "",
    school: str = "",
    degree: str = "",
    graduation_year: str = "",
    city: str = "",
    limit: int = 12,
) -> dict[str, Any]:
    """生成行业快照：岗位地图 + 招聘样本 + 薪资 + 相关专业 + 数据缺口。"""
    try:
        safe_limit = max(1, min(40, int(limit)))
    except (TypeError, ValueError):
        safe_limit = 12

    jobs, warnings = _collect_market(pack, city.strip(), safe_limit)
    roles = _role_market(pack, jobs)
    salary = _salary_stats(jobs)
    outcomes = _load_outcomes(str(pack.get("id", "")))
    major_info = match_major(pack, major)
    gaps: list[str] = []

    if not outcomes:
        gaps.append(
            "同行业/相关专业毕业去向尚未接入：可导入学校就业质量报告或麦可思公开摘要。"
        )
    if not jobs:
        gaps.append("实时招聘样本未获取：需要 BOSS 登录或稍后重试；当前展示行业地图与岗位卡。")
    if not salary.get("count"):
        gaps.append("薪资样本为空：不推断具体数字。")
    if jobs and len(roles) > 5:
        gaps.append("本次只抓取前 5 个岗位族的招聘样本；其余岗位仅展示职责与门槛。")
    if school or degree or graduation_year:
        gaps.append("本次快照未按学校/学历/届别过滤：通用招聘样本不等于同校同届去向。")

    role_names = "、".join(r.get("name", "") for r in roles[:4])
    summary = [
        f"{pack.get('name', '')}：常见方向包括 {role_names} 等。",
        (
            f"本次获取 {len(jobs)} 条当前招聘样本，薪资样本 {salary.get('count', 0)} 条。"
            if jobs
            else "本次未获取实时招聘样本，先看行业地图和岗位卡，不把缺口当结论。"
        ),
        (
            f"你的专业「{major}」在行业中的匹配：{major_info.get('label', major_info['match'])}。"
            if major
            else "未填写专业；专业只用于个性化，不是行业入口。"
        ),
    ]

    return {
        "industry": {
            "id": pack.get("id", ""),
            "name": pack.get("name", ""),
            "description": pack.get("description", ""),
            "subdirections": pack.get("subdirections") or [],
            "related_majors": pack.get("related_majors") or {},
        },
        "input": {
            "major": major,
            "school": school,
            "degree": degree,
            "graduation_year": graduation_year,
            "city": city,
            "limit": safe_limit,
        },
        "major_match": major_info,
        "roles": roles,
        "market": {
            "job_count": len(jobs),
            "salary": salary,
            "source_status": warnings,
        },
        "outcomes": outcomes,
        "benchmarks": pack.get("benchmarks") or [],
        "sources": _source_entries(pack, len(jobs), warnings),
        "gaps": gaps,
        "summary": summary,
        "next_steps": [
            "从 3-5 个岗位中选 1 个，继续看真实 JD 和技能要求。",
            "如果愿意，补充专业/学校/届别，用于后续个性化分析。",
            "想深入时再进入目标选择/规划；扫盲本身不要求简历。",
        ],
        "generated_at": datetime.now().isoformat(),
    }


def outcomes_path(industry_id: str) -> Path:
    """暴露可导入路径，供文档/工具提示。"""
    return DATA_ROOT / "industry_outcomes" / f"{industry_id}.json"
