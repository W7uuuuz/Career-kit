"""学习/求职资源目录：可信链接的唯一来源。

任务 playbook 里的 resources 只能从 ``sop/resources.yaml`` 选；没有收录时
用 ``{"label": "...", "search": "关键词"}`` 兜底，避免模型编造 URL。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

CATALOG_PATH = Path(__file__).resolve().parents[2] / "sop" / "resources.yaml"


@lru_cache(maxsize=1)
def load_catalog() -> tuple[dict[str, Any], ...]:
    """读取资源目录（缓存；文件不存在时返回空）。"""
    if not CATALOG_PATH.exists():
        return ()
    data = yaml.safe_load(CATALOG_PATH.read_text(encoding="utf-8")) or {}
    items = data.get("resources") or []
    return tuple(item for item in items if isinstance(item, dict) and item.get("url"))


def _matches(item: dict[str, Any], tags: set[str]) -> bool:
    item_tags = {str(t) for t in (item.get("tags") or [])}
    return bool(item_tags & tags)


def select_resources(
    tags: list[str] | None = None,
    limit: int = 12,
    priority_tags: list[str] | None = None,
) -> list[dict[str, Any]]:
    """按标签筛选资源；阶段专属标签（priority_tags）优先保留。

    不能直接按 YAML 顺序截断：实习阶段的 boss/nowcoder 很容易被前面的
    算法资源挤出 limit。
    """
    catalog = load_catalog()
    if not tags:
        return [dict(item) for item in catalog[:limit]]
    wanted = {t.lower() for t in tags}
    priority = {t.lower() for t in (priority_tags or [])}

    def score(item: dict[str, Any]) -> tuple[int, int]:
        item_tags = {str(t).lower() for t in (item.get("tags") or [])}
        return (len(item_tags & priority), len(item_tags & wanted))

    chosen = [item for item in catalog if _matches(item, wanted)]
    chosen.sort(key=score, reverse=True)
    return [dict(item) for item in chosen[:limit]]


def catalog_urls() -> set[str]:
    return {str(item["url"]) for item in load_catalog()}


def validate_resources(resources: Any) -> list[str]:
    """校验任务 resources 结构；返回给 LLM 的建议（不阻断保存）。"""
    if not isinstance(resources, list):
        return ["resources 必须是数组，如 [{label, url}] 或 [{label, search}]"]
    warnings: list[str] = []
    known = catalog_urls()
    for i, item in enumerate(resources):
        if not isinstance(item, dict):
            warnings.append(f"resources[{i}] 必须是对象 {{label, url/search}}")
            continue
        label = str(item.get("label") or "").strip()
        url = str(item.get("url") or "").strip()
        search = str(item.get("search") or "").strip()
        if not label:
            warnings.append(f"resources[{i}] 缺 label")
        if url:
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https"):
                warnings.append(f"resources[{i}] 的 url 必须是 http(s)：{url}")
            elif url not in known:
                warnings.append(
                    f"resources[{i}]「{label or url}」不在资源目录中，"
                    "请确认可访问；优先从 detail_current_phase 返回的 resource_catalog 选"
                )
        elif not search:
            warnings.append(f"resources[{i}] 需要 url 或 search 兜底")
    return warnings
