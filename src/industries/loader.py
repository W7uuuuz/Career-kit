"""行业配置加载——只加载解释层，不绑定任何采集实现。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

INDUSTRIES_DIR = Path(__file__).parent


class IndustryError(ValueError):
    """行业配置不可用。"""


@lru_cache(maxsize=1)
def _load_all() -> dict[str, dict[str, Any]]:
    packs: dict[str, dict[str, Any]] = {}
    if not INDUSTRIES_DIR.exists():
        return packs
    for path in sorted(INDUSTRIES_DIR.glob("*.yaml")):
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise IndustryError(f"行业配置读取失败：{path.name}: {exc}") from exc
        if not isinstance(raw, dict) or not raw.get("id"):
            raise IndustryError(f"行业配置缺少 id：{path.name}")
        pack = dict(raw)
        pack["_path"] = str(path)
        packs[str(pack["id"])] = pack
    return packs


def clear_cache() -> None:
    """测试或多语言热更新时清缓存。"""
    _load_all.cache_clear()


def list_industries() -> list[dict[str, Any]]:
    """列出公开可见行业（不暴露内部路径）。"""
    result = []
    for pack in _load_all().values():
        result.append(
            {
                "id": pack.get("id", ""),
                "name": pack.get("name", ""),
                "status": pack.get("status", ""),
                "description": pack.get("description", ""),
                "aliases": list(pack.get("aliases") or []),
            }
        )
    return result


def resolve_industry(raw: str) -> dict[str, Any] | None:
    """按 id / 名称 / 别名解析行业；未知返回 None。"""
    text = str(raw or "").strip().lower()
    if not text:
        return None
    for pack in _load_all().values():
        candidates = [str(pack.get("id", "")), str(pack.get("name", ""))]
        candidates.extend(str(a) for a in (pack.get("aliases") or []))
        if any(text == item.strip().lower() for item in candidates if item):
            return pack
    return None


def get_industry(industry: str) -> dict[str, Any]:
    """解析行业，未知时抛出可读错误。"""
    pack = resolve_industry(industry)
    if pack is None:
        available = ", ".join(p.get("id", "") for p in _load_all().values()) or "无"
        raise IndustryError(
            f"暂不支持行业「{industry}」。可用行业：{available}"
        )
    return pack


def match_major(pack: dict[str, Any], major: str) -> dict[str, Any]:
    """判断专业在行业中的相关性；不把专业当准入门槛。"""
    text = str(major or "").strip()
    if not text:
        return {
            "major": "",
            "match": "unknown",
            "label": "未填写",
            "note": "未填写专业，仅展示行业整体。",
        }
    aliases = pack.get("major_aliases") or {}
    canonical = str(aliases.get(text) or text)
    related = pack.get("related_majors") or {}
    core = [str(x) for x in (related.get("core") or [])]
    adjacent = [str(x) for x in (related.get("adjacent") or [])]
    if canonical in core:
        return {
            "major": text,
            "canonical": canonical,
            "match": "core",
            "label": "核心相关",
            "note": "专业与行业核心岗位直接相关；仍以项目、实习和实际能力为准。",
        }
    if canonical in adjacent:
        return {
            "major": text,
            "canonical": canonical,
            "match": "adjacent",
            "label": "相邻专业",
            "note": "专业与行业相邻；可通过项目、实习或补基础进入。",
        }
    return {
        "major": text,
        "canonical": canonical,
        "match": "cross",
        "label": "跨专业",
        "note": "专业不在核心/相邻清单中；行业仍可能有入口，但需要更明确的证据。",
    }
