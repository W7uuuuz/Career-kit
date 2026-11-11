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
    "电子/半导体": (
        "半导体", "芯片", "集成电路", "数字IC", "模拟IC", "射频", "版图",
        "Verilog", "SystemVerilog", "UVM", "FPGA", "SoC", "MCU", "PCB",
        "EDA", "封装", "良率", "工艺", "器件", "光刻", "刻蚀", "薄膜",
        "MEMS", "CIS",
    ),
    "通信/网络": (
        "通信", "5G", "6G", "光模块", "光通信", "光纤", "基站", "核心网",
        "TCP/IP", "路由", "交换", "天线", "协议", "网络优化", "运营商",
    ),
    "金融/财会": (
        "金融", "投行", "投资银行", "行研", "行业研究", "承做", "承销",
        "并购", "尽调", "尽职调查", "估值", "财务模型", "DCF", "可比公司",
        "量化", "固收", "固定收益", "债券", "基金", "证券", "保险", "精算",
        "风控", "风险管理", "合规", "反洗钱", "理财", "资管", "资产管理",
        "Excel", "Wind", "Bloomberg", "CFA", "CPA", "FRM",
    ),
}

_KEYWORDS: list[str] = [word for group in _KEYWORD_GROUPS.values() for word in group]

_SALARY_RANGE = re.compile(r"(\d+(?:\.\d+)?)\s*[-~–—至]\s*(\d+(?:\.\d+)?)")
_SALARY_NUMBER = re.compile(r"\d+(?:\.\d+)?")
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

_CITY_NAMES: tuple[str, ...] = (
    "北京", "上海", "深圳", "广州", "杭州", "成都", "南京", "武汉", "西安",
    "苏州", "长沙", "重庆", "天津", "合肥", "厦门", "青岛", "郑州", "济南",
    "东莞", "佛山", "珠海", "宁波", "无锡", "福州", "大连", "沈阳", "长春",
    "哈尔滨", "昆明", "南昌", "贵阳", "南宁", "海口", "石家庄", "太原",
    "兰州", "乌鲁木齐", "呼和浩特", "银川", "西宁", "拉萨", "香港", "澳门",
    "台北",
)

_CITY_SUFFIXES = ("总部", "分公司", "研发中心", "办事处", "中心", "基地", "园区")


def _normalize_city(raw: str) -> str:
    city = str(raw or "").strip()
    if not city:
        return ""
    city = _CITY_ALIASES.get(city, city)
    city = _DISTRICT_TO_CITY.get(city, city)
    city = _CITY_ALIASES.get(city, city)
    # 「深圳总部」「上海分公司」这类地点原文先归到城市，避免主城市统计
    # 出现「深圳总部 4」而岗位地点原文是「深圳总部 上海」的不一致（复测 BUG #7）。
    for suffix in _CITY_SUFFIXES:
        if city.endswith(suffix):
            city = city[: -len(suffix)].strip()
            break
    for name in _CITY_NAMES:
        if city.startswith(name):
            return name
    return city


def _jd_text(sample: dict[str, Any]) -> str:
    return " ".join(
        str(sample.get(key) or "")
        for key in ("title", "description", "requirements", "snippet")
    )


def parse_salary(text: Any) -> dict[str, Any] | None:
    """解析薪资原文，区分日薪/月薪/年薪，不做跨口径换算。

    返回 {"type": daily|monthly|annual, "low", "high", "unit"}；
    面议/无数字/无法判断口径时返回 None（宁可留空，不猜）。
    """
    raw = str(text or "").strip()
    if not raw or any(token in raw for token in ("面议", "保密", "未公开")):
        return None
    numbers = _SALARY_NUMBER.findall(raw)
    if not numbers:
        return None
    match = _SALARY_RANGE.search(raw)
    if match:
        low, high = float(match.group(1)), float(match.group(2))
    else:
        low = high = float(numbers[0])
    if low > high:
        low, high = high, low

    lowered = raw.lower()
    if "天" in raw:
        return {"type": "daily", "low": low, "high": high, "unit": "元/天"}
    if "年" in raw:
        return {"type": "annual", "low": low, "high": high, "unit": "万/年"}
    if "万" in raw:
        if "月" in raw:
            return {
                "type": "monthly",
                "low": round(low * 10, 1),
                "high": round(high * 10, 1),
                "unit": "K/月",
            }
        return {"type": "annual", "low": low, "high": high, "unit": "万/年"}
    if "月" in raw or "k" in lowered:
        if "k" not in lowered and low >= 1000 and high >= 1000:
            low, high = low / 1000, high / 1000
        return {"type": "monthly", "low": low, "high": high, "unit": "K/月"}
    return None


def _salary_k(sample: dict[str, Any]) -> tuple[float, float] | None:
    """兼容旧调用：只返回月薪区间（K），日薪/年薪不计入。"""
    parsed = parse_salary(sample.get("salary"))
    if not parsed or parsed["type"] != "monthly":
        return None
    return (float(parsed["low"]), float(parsed["high"]))


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
    daily_lows: list[float] = []
    daily_highs: list[float] = []
    daily_mids: list[float] = []
    annual_lows: list[float] = []
    annual_highs: list[float] = []
    annual_mids: list[float] = []

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

        salary = parse_salary(sample.get("salary"))
        if salary:
            low, high = float(salary["low"]), float(salary["high"])
            if salary["type"] == "daily":
                daily_lows.append(low)
                daily_highs.append(high)
                daily_mids.append((low + high) / 2)
            elif salary["type"] == "annual":
                annual_lows.append(low)
                annual_highs.append(high)
                annual_mids.append((low + high) / 2)
            else:
                salary_lows.append(low)
                salary_highs.append(high)
                salary_mids.append((low + high) / 2)

    with_salary = len(salary_lows) + len(daily_lows) + len(annual_lows)
    salary_digest: dict[str, Any] = {
        "count": with_salary,
        "with_salary": with_salary,
        "monthly_count": len(salary_lows),
        "daily_count": len(daily_lows),
        "annual_count": len(annual_lows),
    }
    if salary_lows:
        salary_digest.update(
            {
                "min_k": round(min(salary_lows), 1),
                "max_k": round(max(salary_highs), 1),
                "median_k": _median(salary_mids),
            }
        )
    if daily_lows:
        salary_digest.update(
            {
                "daily_min": round(min(daily_lows), 1),
                "daily_max": round(max(daily_highs), 1),
                "daily_median": _median(daily_mids),
            }
        )
    if annual_lows:
        salary_digest.update(
            {
                "annual_min_wan": round(min(annual_lows), 1),
                "annual_max_wan": round(max(annual_highs), 1),
                "annual_median_wan": _median(annual_mids),
            }
        )
    salary_digest["monthly"] = {
        "count": len(salary_lows),
        **(
            {
                "min_k": round(min(salary_lows), 1),
                "max_k": round(max(salary_highs), 1),
                "median_k": _median(salary_mids),
                "unit": "K/月",
            }
            if salary_lows
            else {}
        ),
    }
    salary_digest["daily"] = {
        "count": len(daily_lows),
        **(
            {
                "min": round(min(daily_lows), 1),
                "max": round(max(daily_highs), 1),
                "median": _median(daily_mids),
                "unit": "元/天",
            }
            if daily_lows
            else {}
        ),
    }
    salary_digest["annual"] = {
        "count": len(annual_lows),
        **(
            {
                "min_wan": round(min(annual_lows), 1),
                "max_wan": round(max(annual_highs), 1),
                "median_wan": _median(annual_mids),
                "unit": "万/年",
            }
            if annual_lows
            else {}
        ),
    }

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
    monthly_count = salary.get("monthly_count", salary.get("count") or 0)
    if monthly_count:
        lines.append(
            f"- 薪资（月薪）：{monthly_count} 条有数据；"
            f"区间 {salary.get('min_k')}-{salary.get('max_k')}K/月，"
            f"中位 {salary.get('median_k')}K（按下界/上界/中点统计）"
        )
    if salary.get("daily_count"):
        lines.append(
            f"- 薪资（日薪）：{salary['daily_count']} 条有数据；"
            f"区间 {salary.get('daily_min')}-{salary.get('daily_max')} 元/天，"
            f"中位 {salary.get('daily_median')} 元/天（按下界/上界/中点统计）"
        )
    if salary.get("annual_count"):
        lines.append(
            f"- 薪资（年薪）：{salary['annual_count']} 条有数据；"
            f"区间 {salary.get('annual_min_wan')}-{salary.get('annual_max_wan')} 万/年，"
            f"中位 {salary.get('annual_median_wan')} 万/年（按下界/上界/中点统计）"
        )
    if not salary.get("with_salary"):
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
