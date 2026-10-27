"""调研聚合洞察——确定性统计（不调 LLM、不生成判断）。

大量 JD 详情不能直接塞给模型：先用这份「结构化摘要 + 花名册」让父 agent
或子 agent 快速判断哪些值得深读，再按 id 取全文（read_research_details）。

洞察只陈述事实：词频=多少条 JD 提到该词，不代表重要性排序；缺数据如实留空。
"""

from __future__ import annotations

import re
from typing import Any

# 领域关键词（需求侧高频词表）：按「提及的 JD 数」计频，不按出现次数堆量。
# 维护原则：只放可被 JD 文本直接命中的技能/条件词，不做语义推断。
_KEYWORD_GROUPS: dict[str, tuple[str, ...]] = {
    "语言/工程": (
        "Python", "Java", "Go", "Golang", "C++", "C#", "TypeScript", "JavaScript",
        "Rust", "SQL", "Shell", "Linux", "Git", "Docker", "Kubernetes",
    ),
    "AI/算法": (
        "LLM", "大模型", "Agent", "RAG", "LangChain", "LangGraph", "LlamaIndex",
        "Prompt", "提示词", "微调", "Fine-tune", "Transformer", "Embedding",
        "向量", "多模态", "NLP", "CV", "推荐", "搜索", "评测", "推理", "训练",
    ),
    "后端/数据": (
        "后端", "前端", "全栈", "微服务", "分布式", "高并发", "数据库", "MySQL",
        "Redis", "Kafka", "消息队列", "缓存", "API", "性能优化", "架构",
    ),
    "产品/协作": (
        "产品", "需求分析", "用户研究", "项目管理", "跨团队", "沟通", "协作",
        "英语", "论文", "开源",
    ),
}

_KEYWORDS: list[str] = [word for group in _KEYWORD_GROUPS.values() for word in group]

_SALARY_RANGE_K = re.compile(r"(\d+(?:\.\d+)?)\s*[-~–]\s*(\d+(?:\.\d+)?)\s*[kK]")
_SALARY_SINGLE_K = re.compile(r"(\d+(?:\.\d+)?)\s*[kK]")
_CITY_SPLIT = re.compile(r"[、,，/|·\s]+")

# 城市归一：后缀与常见行政区（避免「上海/上海市」「徐汇区」被重复计数）
_CITY_ALIASES = {
    "上海市": "上海", "北京市": "北京", "深圳市": "深圳", "杭州市": "杭州",
    "广州市": "广州", "成都市": "成都", "南京市": "南京", "武汉市": "武汉",
}
_DISTRICT_TO_CITY = {
    "徐汇区": "上海", "浦东新区": "上海", "静安区": "上海", "黄浦区": "上海",
    "长宁区": "上海", "杨浦区": "上海", "闵行区": "上海", "海淀区": "北京",
    "朝阳区": "北京", "西城区": "北京", "东城区": "北京", "南山区": "深圳",
    "福田区": "深圳", "宝安区": "深圳", "余杭区": "杭州", "西湖区": "杭州",
}


def _normalize_city(raw: str) -> str:
    city = str(raw or "").strip()
    if not city:
        return ""
    city = _CITY_ALIASES.get(city, city)
    city = _DISTRICT_TO_CITY.get(city, city)
    return _CITY_ALIASES.get(city, city)


def _jd_text(sample: dict[str, Any]) -> str:
    return " ".join(
        str(sample.get(key) or "")
        for key in ("title", "description", "requirements", "snippet")
    )


def _salary_k(sample: dict[str, Any]) -> tuple[float, float] | None:
    """解析月薪区间（K）；日薪/年薪/面议不计入，避免口径混杂。"""
    text = str(sample.get("salary") or "")
    if "天" in text or "年" in text:
        return None
    match = _SALARY_RANGE_K.search(text)
    if match:
        low, high = float(match.group(1)), float(match.group(2))
        return (low, high) if low <= high else (high, low)
    match = _SALARY_SINGLE_K.search(text)
    if match:
        value = float(match.group(1))
        return (value, value)
    return None


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return round((ordered[mid - 1] + ordered[mid]) / 2, 1)


def build_digest(
    jd_samples: list[dict[str, Any]],
    cases: list[dict[str, Any]],
    dropped_no_detail: int = 0,
    *,
    raw_case_count: int | None = None,
) -> dict[str, Any]:
    """聚合洞察：城市/薪资/高频要求/学历与层级信号/案例结构。"""
    city_counts: dict[str, int] = {}
    multi_city_jd_count = 0
    keyword_counts: dict[str, int] = {}
    education_mentions = {"本科": 0, "硕士": 0, "博士": 0, "985": 0, "211": 0, "双非": 0}
    level_signals = {"实习": 0, "校招": 0, "社招": 0}
    salary_lows: list[float] = []
    salary_highs: list[float] = []
    salary_mids: list[float] = []

    for sample in jd_samples:
        text = _jd_text(sample)
        lowered = text.lower()

        locations = [
            _normalize_city(city)
            for city in _CITY_SPLIT.split(str(sample.get("location") or ""))
            if _normalize_city(city)
        ]
        if locations:
            primary = locations[0]
            city_counts[primary] = city_counts.get(primary, 0) + 1
            if len(set(locations)) > 1:
                multi_city_jd_count += 1

        for keyword in _KEYWORDS:
            if keyword.lower() in lowered:
                keyword_counts[keyword] = keyword_counts.get(keyword, 0) + 1

        # 学历信号：优先看要求段，避免把公司介绍/标题里的词当硬性要求
        edu_text = str(
            sample.get("requirements") or sample.get("description")
            or sample.get("snippet") or ""
        )
        for label in education_mentions:
            if label in edu_text:
                education_mentions[label] += 1

        title = str(sample.get("title") or "")
        if "实习" in title:
            level_signals["实习"] += 1
        elif "校招" in title or "应届" in title:
            level_signals["校招"] += 1
        elif "社招" in title:
            level_signals["社招"] += 1

        salary = _salary_k(sample)
        if salary:
            low, high = salary
            salary_lows.append(low)
            salary_highs.append(high)
            salary_mids.append((low + high) / 2)

    salary_digest: dict[str, Any] = {"count": len(salary_lows)}
    if salary_lows:
        salary_digest.update(
            {
                "min_k": round(min(salary_lows), 1),
                "max_k": round(max(salary_highs), 1),
                "median_k": _median(salary_mids),
            }
        )

    case_kinds: dict[str, int] = {}
    for case in cases:
        kind = str(case.get("kind") or "unknown")
        case_kinds[kind] = case_kinds.get(kind, 0) + 1

    return {
        "jd_count": len(jd_samples),
        "case_count": len(cases),
        "case_count_raw": raw_case_count if raw_case_count is not None else len(cases),
        "dropped_no_detail": dropped_no_detail,
        "cities": [
            {"city": city, "count": count}
            for city, count in sorted(city_counts.items(), key=lambda kv: -kv[1])[:5]
        ],
        "multi_city_jd_count": multi_city_jd_count,
        "salary": salary_digest,
        "top_requirements": [
            {"term": term, "count": count}
            for term, count in sorted(keyword_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:10]
        ],
        "education_mentions": {k: v for k, v in education_mentions.items() if v},
        "level_signals": {k: v for k, v in level_signals.items() if v},
        "case_kinds": case_kinds,
    }


def render_digest_lines(digest: dict[str, Any]) -> list[str]:
    """洞察 → 紧凑文本（给 LLM 读，控制在十几行内）。"""
    if not digest:
        return []
    jd_count = digest.get("jd_count") or 0
    case_count = digest.get("case_count") or 0
    if not jd_count and not case_count:
        return []

    lines = ["【聚合洞察（确定性统计，非语义结论）】"]
    sample_line = f"- 样本：{jd_count} 条有详情 JD"
    dropped = digest.get("dropped_no_detail") or 0
    if dropped:
        sample_line += f"（另有 {dropped} 条无详情已剔除）"
    kinds = digest.get("case_kinds") or {}
    if case_count:
        kind_bits = "、".join(f"{k} {v}" for k, v in kinds.items())
        sample_line += f"；案例 {case_count} 条（{kind_bits}）"
    lines.append(sample_line)

    cities = digest.get("cities") or []
    if cities:
        line = "- 城市（主城市）：" + "、".join(
            f"{c['city']} {c['count']}" for c in cities
        )
        multi = digest.get("multi_city_jd_count") or 0
        if multi:
            line += f"；多城市岗位 {multi} 条"
        lines.append(line)

    salary = digest.get("salary") or {}
    if salary.get("count"):
        lines.append(
            f"- 薪资：{salary['count']} 条有数据；"
            f"区间 {salary.get('min_k')}-{salary.get('max_k')}K/月，"
            f"中位 {salary.get('median_k')}K（按下界/上界/中点统计）"
        )
    else:
        lines.append("- 薪资：本次岗位均未公开薪资（数据缺口，不推断）")

    terms = digest.get("top_requirements") or []
    if terms:
        lines.append(
            "- 高频要求（按提及 JD 数）："
            + " · ".join(f"{t['term']} {t['count']}" for t in terms)
        )

    edu = digest.get("education_mentions") or {}
    if edu:
        lines.append(
            "- 学历提及次数（要求段关键词，非硬性门槛）："
            + "、".join(f"{k} {v}" for k, v in edu.items())
        )

    levels = digest.get("level_signals") or {}
    if levels:
        lines.append("- 层级信号：" + "、".join(f"{k} {v}" for k, v in levels.items()))

    return lines
