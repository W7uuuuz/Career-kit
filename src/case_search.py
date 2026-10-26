"""案例搜寻聚合器——search_cases 工具的逻辑层。

三类源聚合为统一案例卡：
1. local      —— data/knowledge/ 本地积累（此前抓过的 JD/面经/经验帖 + 用户手放）
2. nowcoder   —— 牛客面经（成功经验/面试题主矿）
3. github     —— GitHub 秋招经验帖（开源无墙，标题自述学历）
4. official   —— company 匹配到的官方/BOSS 源的岗位 JD（面试要求口径；boss 含薪资+学历参数）

纪律：
- 各源独立失败不拖死，失败进 warnings 如实上报；
- 不编造数据——任何卡片必有真实 url 或本地路径可溯源；
- 学历条件（五档四层）存在时按命中强度排序，无命中不报假匹配。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .education import (
    canonical_education,
    education_match_beta,
    education_search_words,
    normalize_education_tag,
)
from .paths import KNOWLEDGE_DIR
from .tools.knowledge_search import search_knowledge as _search_local

# 公司别名 → 官方源 scraper id（search_cases 的 company 参数路由用）
_COMPANY_ALIASES: dict[str, str] = {
    "字节": "bytedance",
    "字节跳动": "bytedance",
    "腾讯": "tencent",
    "百度": "baidu",
    "阿里": "alibaba",
    "阿里巴巴": "alibaba",
    "boss": "boss",
    "boss直聘": "boss",
}

_RECENT_DAYS = 730  # 近两年新鲜度全额分，之后线性衰减


def collect_cases(
    role: str,
    company: str = "",
    city: str = "",
    education: str = "",
    kind: str = "both",
    limit: int = 12,
) -> dict[str, Any]:
    """聚合多个源的案例卡（阻塞函数，MCP 工具层负责丢线程）。

    Returns:
        {
            "cases": [...],          # 排序后卡片
            "warnings": [...],       # 源失败/部分失败警示
            "sources": {slug: {"count": n}},
        }
    """
    warnings: list[str] = []
    sources_count: dict[str, int] = {}
    raw_items: list[dict[str, Any]] = []

    edu_condition = None
    if education:
        try:
            edu_condition = canonical_education(education)
        except ValueError as e:
            return {"cases": [], "warnings": [str(e)], "sources": {}}

    role = (role or "").strip()
    if not role:
        return {"cases": [], "warnings": ["role（岗位方向）为空"], "sources": {}}

    def _feed(slug: str, rows_or_error: Any) -> None:
        """统一消费 loader.search_company_jobs 的返回：错误进 warnings，结果打汇聚。"""
        if not isinstance(rows_or_error, dict):
            return
        if rows_or_error.get("error") or rows_or_error.get("count", 0) == 0:
            msg = rows_or_error.get("error") or "无结果"
            warnings.append(f"{slug}: {msg}")
            sources_count[slug] = 0
            return
        rows = rows_or_error.get("results") or []
        sources_count[slug] = len(rows)
        for r in rows:
            if isinstance(r, dict) and not r.get("error"):
                raw_items.append(r)

    # ---- 源 1：本地知识库（零成本，总查） ----
    try:
        local_words = education_search_words(edu_condition) if edu_condition else []
        local_query = " ".join(
            filter(None, [
                *local_words,
                company,
                role,
                "面经 offer 案例",
            ])
        )
        local = _search_local(local_query)
        rows = local.get("results") or []
        sources_count["local"] = len(rows)
        for r in rows:
            if isinstance(r, dict) and r.get("source"):
                raw_items.append({
                    **_local_row_to_item(r),
                    "company": "",
                    "position": "",
                    "location": "",
                })
    except Exception as e:  # 本地读失败不该拖死
        warnings.append(f"local: {e}")
        sources_count["local"] = 0

    # ---- 源 2：牛客面经 ----
    _feed("nowcoder", _search_slug("nowcoder", role, company, edu_condition))

    # ---- 源 3：GitHub 经验帖 ----
    _feed("github", _search_slug("github", role, company, edu_condition, education_raw=education))

    # ---- 源 4：company 匹配的官方/BOSS 源（面试要求） ----
    if company:
        slug = _COMPANY_ALIASES.get(company.lower(), "")
        if slug and slug not in {"nowcoder", "github"}:
            _feed(slug, _search_official(slug, role, city, edu_condition))

    cards = [_row_to_card(r) for r in raw_items]
    cards = [c for c in cards if c]

    ranked = _rank(cards, edu_condition, kind, limit)
    return {"cases": ranked, "warnings": warnings, "sources": sources_count}


def _search_slug(
    slug: str,
    role: str,
    company: str,
    edu_condition: dict | None,
    education_raw: str = "",
) -> dict[str, Any] | None:
    """调 loader.search_company_jobs 的薄弱封装（测试时 monkeypatch 这里）。"""
    role_main = _first_role_token(role)
    if not role_main:
        return None
    kwargs: dict[str, Any] = {"keyword": role_main, "limit": 12}
    if company:
        kwargs["filter_company"] = company
    if edu_condition:
        words = education_search_words(edu_condition)
        if slug == "github" and education_raw:
            kwargs["education"] = education_raw
        elif slug == "nowcoder" and words:
            kwargs["keyword"] = f"{role_main} {words[0]}"
    from .scrapers.loader import search_company_jobs

    return search_company_jobs(slug, **kwargs)


def _search_official(
    slug: str,
    role: str,
    city: str,
    edu_condition: dict | None,
) -> dict[str, Any] | None:
    """官方/BOSS 源按面试要求口径抓取；boss 支持 degree 学历过滤与薪资。"""
    if not (role_main := _first_role_token(role)):
        return None
    kwargs: dict[str, Any] = {"keyword": role_main, "limit": 8}
    if city:
        kwargs["city"] = city
    if slug == "boss" and edu_condition:
        words = education_search_words(edu_condition)
        degree = edu_condition.get("degree") or ""
        if degree == "硕士":
            kwargs["degree"] = "硕士"
        elif degree == "本科" and ("双非" not in words):
            kwargs["degree"] = "本科"
    from .scrapers.loader import search_company_jobs

    return search_company_jobs(slug, **kwargs)


def _first_role_token(role: str) -> str:
    """把长 role（如 "AI Agent 开发工程师"）裁成搜索友好的短词——AI 型词组保留前 2 段。"""
    role = (role or "").strip()
    if len(role) <= 8:
        return role
    # 取前两个逻辑词：中文按空格切，尽量保 AI 时代的连续词组
    parts = role.replace("工程师", "").replace("开发", "").strip().split()
    if parts and len("".join(parts[:2])) >= 2:
        return " ".join(parts[:2])[:20]
    return role[:8]


def _local_row_to_item(row: dict) -> dict:
    """search_knowledge 的命中 → 统一 item 轮廓。"""
    src = row.get("source", "")
    content = row.get("content", "")
    meta: dict[str, Any] = {}
    full_path = KNOWLEDGE_DIR / src

    if src.endswith(".json") and full_path.exists():
        try:
            meta = json.loads(full_path.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
    else:
        # md 面经：只看 front-matter 行
        for line in content.splitlines()[:12]:
            if line.startswith(("source:", "url:", "company:", "position:", "date:", "round:")):
                key, _, value = line.partition(":")
                meta[key.strip()] = value.strip()

    return {
        "title": meta.get("title") or Path(src).stem,
        "url": meta.get("url", ""),
        "snippet": _md_meta_strip(content)[:280],
        "date": str(meta.get("date") or meta.get("_fetched_at") or "")[:10],
        "source": meta.get("source", "") or ("github" if "/experiences/github/" in src else "local"),
        "education_tag": meta.get("education_tag", ""),
        "year_tag": meta.get("year_tag", ""),
        "local_path": str(full_path),
        "_rel_path": src,
    }


def _md_meta_strip(content: str) -> str:
    """md 面经正文从 front-matter 之后开始。"""
    if content.startswith("---"):
        end = content.find("---", 3)
        if end > 0:
            return content[end + 3:].strip()
    return content


def _row_to_card(row: dict) -> dict | None:
    """统一 item（官方/牛客/GitHub/本地）→ 案例卡。规划好的字段一次成型。"""
    source = (row.get("source") or "").lower()
    title = (row.get("title") or "").strip()
    if not title:
        return None

    if source in {"github", "nowcoder"} or "/interviews/" in row.get("_rel_path", ""):
        text = f"{title} {row.get('snippet', '')[:400]}"
        tag = normalize_education_tag(text)
        kind = "interview_requirements" if any(
            w in text for w in ("面经", "复盘", "面试", "一面", "二面", "三面", "HR面")
        ) else "success_experience"
        return _card({
            "kind": kind,
            "title": title,
            "source": source or "local",
            "url": row.get("url", ""),
            "date": row.get("date", ""),
            "education_tag": row.get("education_tag") or tag["tag"],
            "year_tag": row.get("year_tag") or tag["year"],
            "highlights": _highlights(row, kind),
        })

    # 官方/BOSS 岗位 JD → 面试要求口径
    return _card({
        "kind": "interview_requirements",
        "title": title,
        "source": source or "official",
        "url": row.get("url", ""),
        "date": "",
        "education_tag": "",
        "year_tag": "",
        "highlights": _highlights(row, "interview_requirements"),
        "salary": row.get("salary", ""),
        "location": row.get("location", ""),
    })


def _highlights(row: dict, kind: str) -> list[str]:
    """卡片要点：jd 摘要 / 面试题线索 / 帖子正文前几句。"""
    summary = (row.get("summary") or row.get("snippet") or "").strip()
    if summary:
        return [s.strip() for s in summary.splitlines() if s.strip()][:3]
    return []


def _card(base: dict) -> dict:
    card = {
        "kind": base["kind"],
        "title": base["title"],
        "source": base["source"],
        "url": base.get("url") or "",
        "date": base.get("date") or "",
        "background": {
            "education_tag": base.get("education_tag") or "",
            "year": base.get("year_tag") or "",
            "company": base.get("company", "") or "",
            "position": base.get("position", "") or "",
        },
        "highlights": base.get("highlights") or [],
    }
    if base.get("salary"):
        card["salary"] = base["salary"]
    if base.get("location"):
        card["location"] = base["location"]
    if base.get("local_path"):
        card["local_path"] = base["local_path"]
    return card


def _rank(
    cards: list[dict],
    edu_condition: dict | None,
    kind: str,
    limit: int,
) -> list[dict]:
    """去重 → 学历命中/新鲜度打分 → kind 分组内排序输出。"""
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    unique: list[tuple[dict, float]] = []

    kind_wanted = kind or "both"
    if kind_wanted == "success":
        allowed = {"success_experience"}
    elif kind_wanted == "requirements":
        allowed = {"interview_requirements"}
    else:
        allowed = {"success_experience", "interview_requirements"}

    now = datetime.now(UTC)
    for card in cards:
        if card["kind"] not in allowed:
            continue
        url_key = (card["url"] or f"local::{card['title']}").replace("https://", "").rstrip("/")
        title_key = "".join(card["title"].lower().split())[:60]
        if url_key in seen_urls or title_key in seen_titles:
            continue
        seen_urls.add(url_key)
        seen_titles.add(title_key)

        score = 0.0
        if edu_condition:
            beta = education_match_beta(edu_condition, card["title"])
            if beta == 0 and card["background"].get("education_tag"):
                beta = education_match_beta(edu_condition, card["background"]["education_tag"])
            score += beta * 2.0
        score += _freshness(card.get("date", ""), now)
        score += min(len(card.get("highlights") or []), 3) * 0.1
        unique.append((card, round(score, 2)))

    unique.sort(key=lambda x: x[1], reverse=True)
    ranked = []
    for card, score in unique:
        card["match_score"] = score if edu_condition else None
        ranked.append(card)
        if len(ranked) >= limit:
            break
    # match_score=None 显式拨掉（JSON 输出干净）
    for card in ranked:
        if card["match_score"] is None:
            card.pop("match_score", None)
    return ranked


def _freshness(date_str: str, now: datetime) -> float:
    """近两年内 1.0 → 逐年线性衰减到 0。"""
    if not date_str:
        return 0.0
    try:
        d = datetime.fromisoformat(str(date_str)[:10]).replace(tzinfo=UTC)
    except ValueError:
        return 0.0
    days = (now - d).days
    if days < 0:
        return 1.0
    if days <= _RECENT_DAYS:
        return 1.0
    decay = 1.0 - (days - _RECENT_DAYS) / (_RECENT_DAYS * 2)
    return max(decay, 0.0)


def render_cases(result: dict[str, Any], role: str, education: str, company: str) -> str:
    """聚合结果 → 给 LLM 直接转述的文本（案例卡按组展示带来源）。"""
    cases = result.get("cases") or []
    warnings = result.get("warnings") or []
    sources = result.get("sources") or {}

    header = (
        f"【案例搜寻】role={role}"
        + (f" education={education}" if education else "")
        + (f" company={company}" if company else "")
    )

    if not cases:
        lines = [header, "", "所有来源均未命中案例/岗位要求，或全部失败。来源状态："]
        for slug, count in (sources or {}).items():
            lines.append(f"- {slug}: {count} 条")
        if warnings:
            lines.append("失败/缺失：")
            for w in warnings:
                lines.append(f"- {w}")
        lines.extend([
            "",
            "下一步建议（如实告知用户，不编造）：",
            "1. 放宽条件重搜（education 或 company 置空试试）",
            "2. fetch_company_jobs 用不同关键词抓目标企业",
            "3. 用户手头有案例/Q&A 材料就 import_jd / import_jd_file 导入",
        ])
        return "\n".join(lines)

    success = [c for c in cases if c["kind"] == "success_experience"]
    requirements = [c for c in cases if c["kind"] == "interview_requirements"]

    lines = [header]
    lines.append(f"— 共 {len(cases)} 条（成功经验 {len(success)} · 面试要求 {len(requirements)}）")
    lines.append("来源：" + " ".join(f"{slug}={n}" for slug, n in sources.items()))

    if success:
        lines.extend(["", "## 同背景成功经验"])
        for i, c in enumerate(success, 1):
            lines.extend(_case_line(i, c))
    if requirements:
        lines.extend(["", "## 面试要求（JD/面经口径）"])
        for i, c in enumerate(requirements, 1):
            lines.extend(_case_line(i, c))

    if warnings:
        lines.extend(["", "部分来源失败（如实告知用户）："])
        for w in warnings:
            lines.append(f"- {w}")

    lines.extend([
        "",
        "向用户展示案例卡时必须标明来源（平台/名称/时间）——不标注来源不诚实。",
        "需要详情深挖：fetch_jd_detail(url=...)（案例详情全文）。",
        "这些案例的共性要求将作为差距分析的核心输入，别漏出 match_score 校准与 red flags。",
    ])
    return "\n".join(lines)


def _case_line(i: int, c: dict) -> list[str]:
    bg = c.get("background") or {}
    meta = [c.get("source", ""), bg.get("education_tag", ""), bg.get("year", ""),
            c.get("date", ""), c.get("salary", ""), c.get("location", "")]
    meta_str = " | ".join(m for m in meta if str(m).strip())
    lines = [f"{i}. **{c['title']}**（{meta_str or '无元数据'}）"]
    if c.get("url"):
        lines.append(f"   来源：{c['url']}")
    elif c.get("local_path"):
        lines.append(f"   本地文件：{c['local_path']}")
    for h in (c.get("highlights") or [])[:2]:
        lines.append(f"   - {h[:150]}")
    return lines
