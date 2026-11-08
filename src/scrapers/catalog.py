"""企业目录查询层——档位、行业与 scraper 映射。

数据源：`companies.yaml`（企业元数据）+ `config.yaml`（scraper 注册表）。
本模块只做只读查询，不触发任何网络请求；catalog 与 scraper 的对应关系
在读取时校验：配置里存在但目录缺失的 scraper 视为「未收录」，不阻断启动。
"""

from __future__ import annotations

from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

COMPANIES_PATH = Path(__file__).parent / "companies.yaml"
CONFIG_PATH = Path(__file__).parent / "config.yaml"

TIER_ORDER: dict[str, int] = {"大厂": 4, "中厂": 3, "小厂": 2, "未收录": 1}
PLATFORM_IDS: frozenset[str] = frozenset({"boss", "nowcoder", "github"})


def _read_yaml(path: Path) -> Any:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    return raw


@lru_cache(maxsize=1)
def _scraper_ids() -> frozenset[str]:
    data = _read_yaml(CONFIG_PATH)
    if not isinstance(data, dict):
        return frozenset()
    scrapers = data.get("scrapers")
    if not isinstance(scrapers, dict):
        return frozenset()
    return frozenset(str(k) for k in scrapers)


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _normalize_entry(raw: dict[str, Any]) -> dict[str, Any] | None:
    company_id = str(raw.get("id") or "").strip()
    if not company_id:
        return None
    scrapers = _as_list(raw.get("scrapers"))
    if not scrapers:
        scrapers = _as_list(raw.get("scraper"))
    registered = _scraper_ids()
    available = [s for s in scrapers if s in registered]
    return {
        "id": company_id,
        "name": str(raw.get("name") or company_id).strip(),
        "tier": str(raw.get("tier") or "未收录").strip(),
        "industry": str(raw.get("industry") or "").strip(),
        "aliases": _as_list(raw.get("aliases")),
        "scrapers": scrapers,
        "available_scrapers": available,
        "scrapable": bool(available),
        "careers_url": str(raw.get("careers_url") or "").strip(),
    }


@lru_cache(maxsize=1)
def _catalog() -> tuple[dict[str, Any], ...]:
    data = _read_yaml(COMPANIES_PATH)
    if not isinstance(data, dict):
        return ()
    raw_items = data.get("companies")
    if not isinstance(raw_items, list):
        return ()
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        entry = _normalize_entry(raw)
        if entry is None or entry["id"].lower() in seen:
            continue
        seen.add(entry["id"].lower())
        entries.append(entry)
    return tuple(entries)


def reload_catalog() -> None:
    """清空缓存（测试或运行期修改目录后使用）。"""
    _catalog.cache_clear()
    _scraper_ids.cache_clear()


def all_companies() -> list[dict[str, Any]]:
    """返回目录副本，调用方可安全修改。"""
    return [dict(item, aliases=list(item["aliases"]), scrapers=list(item["scrapers"]),
                 available_scrapers=list(item["available_scrapers"]))
            for item in _catalog()]


def _tier_filter(tier: str | Iterable[str] | None) -> set[str]:
    if not tier:
        return set()
    if isinstance(tier, str):
        return {part.strip() for part in tier.replace("，", ",").split(",") if part.strip()}
    return {str(part).strip() for part in tier if str(part).strip()}


def list_companies(
    tier: str | Iterable[str] | None = None,
    industry: str | None = None,
    scrapable_only: bool = False,
) -> list[dict[str, Any]]:
    """按档位/行业筛选企业；档位按 大厂 > 中厂 > 小厂 > 未收录 排序。"""
    tiers = _tier_filter(tier)
    industry_norm = (industry or "").strip()
    result = []
    for item in all_companies():
        if tiers and item["tier"] not in tiers:
            continue
        if industry_norm and industry_norm not in item["industry"]:
            continue
        if scrapable_only and not item["scrapable"]:
            continue
        result.append(item)
    result.sort(key=lambda it: (-TIER_ORDER.get(it["tier"], 0), it["name"]))
    return result


def get_company(identifier: str) -> dict[str, Any] | None:
    """按 id / 名称 / 别名 / scraper id 查企业；找不到返回 None。"""
    key = (identifier or "").strip().lower()
    if not key:
        return None
    for item in all_companies():
        if key == item["id"].lower():
            return item
    for item in all_companies():
        if key == item["name"].lower():
            return item
    for item in all_companies():
        if any(key == alias.lower() for alias in item["aliases"]):
            return item
    for item in all_companies():
        if key in {s.lower() for s in item["scrapers"]}:
            return item
    return None


def company_for_scraper(scraper_id: str) -> dict[str, Any] | None:
    """scraper id → 企业目录条目。"""
    key = (scraper_id or "").strip().lower()
    if not key:
        return None
    for item in all_companies():
        if key in {s.lower() for s in item["scrapers"]}:
            return item
    return None


def tier_for_scraper(scraper_id: str) -> str:
    """scraper id → 档位；平台类源返回「平台」，未收录返回「未收录」。"""
    key = (scraper_id or "").strip().lower()
    if key in PLATFORM_IDS:
        return "平台"
    company = company_for_scraper(key)
    return company["tier"] if company else "未收录"


def tier_rank(tier: str) -> int:
    return TIER_ORDER.get((tier or "").strip(), 0)


def catalog_summary() -> dict[str, Any]:
    """目录概览：各档位企业数、可抓取数、各行业数。"""
    items = all_companies()
    by_tier: dict[str, int] = {}
    by_tier_scrapable: dict[str, int] = {}
    by_industry: dict[str, int] = {}
    for item in items:
        by_tier[item["tier"]] = by_tier.get(item["tier"], 0) + 1
        if item["scrapable"]:
            by_tier_scrapable[item["tier"]] = by_tier_scrapable.get(item["tier"], 0) + 1
        if item["industry"]:
            by_industry[item["industry"]] = by_industry.get(item["industry"], 0) + 1
    return {
        "total": len(items),
        "scrapable": sum(1 for item in items if item["scrapable"]),
        "by_tier": by_tier,
        "by_tier_scrapable": by_tier_scrapable,
        "by_industry": by_industry,
    }
