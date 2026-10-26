"""学历标签归一——案例匹配的公共依赖。

五档（学校层次）× 四层（学位层级）× 届别：
- 档位：985 / 211 / 双非（含普通一本、二本、三本，归并）/ 专科
- 层级：博士 / 硕士 / 本科 / 专科
- 届别：如「27 届」「2027 届」

「海归/合作办学」v1 不做精确匹配——未识别时如实标注，仍参与搜索但不加分。
所有线索从中文文本（标题/正文/用户自述）中正则抽取，无外部数据依赖。
"""

from __future__ import annotations

import re
from typing import Any

# 层级（学位）归一：长词优先，短词兜底（标题里大量「双非本」「985硕」简写）
_DEGREE_PATTERNS: list[tuple[str, str]] = [
    ("博士", "博士"),
    ("研究生", "硕士"),
    ("硕士", "硕士"),
    ("本科", "本科"),
    ("专科", "专科"),
    ("大专", "专科"),
    ("高职", "专科"),
    ("硕", "硕士"),
    ("博", "博士"),
    ("本", "本科"),
    ("专", "专科"),
]

# 档位（学校层次）归一：长词优先
_TIER_PATTERNS: list[tuple[str, str]] = [
    ("985", "985"),
    ("211", "211"),
    ("双非", "双非"),
    ("普通一本", "双非"),
    ("普本", "双非"),
    ("普通本科", "双非"),
    ("一本", "双非"),
    ("二本", "双非"),
    ("三本", "双非"),
]

# 搜索词：升级某档位时的常用表述 + GitHub issue 标题里常见的写法
_TIER_SEARCH_WORDS: dict[str, tuple[str, ...]] = {
    "985": ("985",),
    "211": ("211",),
    "双非": ("双非", "普本", "普一", "普二", "普三", "二本", "三本", "普通本科", "一本"),
}
_DEGREE_SEARCH_WORDS: dict[str, tuple[str, ...]] = {
    "博士": ("博士", "博"),
    "硕士": ("硕士", "研究生", "硕"),
    "本科": ("本科", "本"),
    "专科": ("专科", "大专", "专"),
}

# 层级标签缩写（惯例：「双非本」「211硕」）
_DEGREE_TAG_CHAR = {"博士": "博", "硕士": "硕", "本科": "本", "专科": "专"}

# 届别：27届 / 2027届 / 27 届；级（入学）也记录（当前届 = 级 + 依次）
_YEAR_PATTERN = re.compile(r"(20\d{2}|\d{2})\s*([届级])")


def _compose_tag(tier: str, degree: str) -> str:
    if tier and degree:
        return f"{tier}{_DEGREE_TAG_CHAR.get(degree, '')}"
    return tier or degree


def normalize_education_tag(text: str) -> dict[str, Any]:
    """从文本抽取学历线索并归一。

    Returns:
        {
            "tier": "985/211/双非" 或 ""（未识别）,
            "degree": "博士/硕士/本科/专科" 或 "",
            "tag": "双非本/211硕" 组合标签（两者都有时），
            "year": "27届" 原始串 或 "",
            "explicit": bool——tier 或 degree 至少识别到一个，
        }
    """
    tier = _extract_first(text, _TIER_PATTERNS)
    degree = _extract_first(text, _DEGREE_PATTERNS)
    year = _extract_year(text)
    tag = _compose_tag(tier, degree)

    return {
        "tier": tier,
        "degree": degree,
        "tag": tag,
        "year": year,
        "explicit": bool(tier or degree or year),
    }


def canonical_education(raw: str) -> dict[str, Any]:
    """把用户输入的教育条件归一为结构化条件（区别于 normalize_education_tag 的''抽取''）。

    语义：调用方明确给了学历条件——未识别时 raise ValueError，让工具返回可读的参数纠错。
    """
    text = (raw or "").strip().lower()
    if not text:
        raise ValueError("education 为空")
    tier = _extract_first(text, _TIER_PATTERNS)
    degree = _extract_first(text, _DEGREE_PATTERNS)
    if not tier and not degree:
        raise ValueError(
            f"education「{raw}」无法归一——支持 985/211/双非（普本/一本/二本/三本）/专科"
            "与 博士/硕士/本科/专科学力层级，例：「双非本」「211硕」「专升本」"
        )
    tag = _compose_tag(tier, degree)
    return {"tier": tier, "degree": degree, "tag": tag}


def education_match_beta(condition: dict[str, Any], text: str) -> int:
    """给定教育条件在文本中的匹配强度。

    Returns:
        3 = tag 完全命中（档位与层级都一致）
        2 = 仅档位同档
        1 = 仅层级同层
        0 = 未命中或条件不完整
    """
    info = normalize_education_tag(text)
    if not info["explicit"]:
        return 0

    cond_tier = condition.get("tier") or ""
    cond_degree = condition.get("degree") or ""
    tier_ok = bool(cond_tier) and info["tier"] == cond_tier
    degree_ok = bool(cond_degree) and info["degree"] == cond_degree

    if tier_ok and degree_ok:
        return 3
    if tier_ok:
        return 2
    if degree_ok:
        return 1
    return 0


def education_search_words(condition: dict[str, Any]) -> list[str]:
    """把归一后的教育条件展开成搜索关键词串（供在线搜索拼 query）。

    例：「双非本」→ ["双非", "二本", "普本", "本科"]——搜索引擎 OR 命中宽，
    由聚合层再精确打分。
    """
    words: list[str] = []
    tier = condition.get("tier") or ""
    degree = condition.get("degree") or ""
    if tier:
        words.extend(_TIER_SEARCH_WORDS.get(tier, (tier,)))
    if degree:
        words.extend(_DEGREE_SEARCH_WORDS.get(degree, (degree,)))
    if not words:
        return []
    return words


def _extract_first(text: str, patterns: list[tuple[str, str]]) -> str:
    low = text.lower()
    for pattern, canonical in patterns:
        if pattern in low:
            return canonical
    return ""


def _extract_year(text: str) -> str:
    m = _YEAR_PATTERN.search(text)
    if not m:
        return ""
    return f"{m.group(1)}{m.group(2)}"
