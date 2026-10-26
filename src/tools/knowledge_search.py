"""知识库检索——搜索本地积累的求职资料。

只检索用户主目录 ~/.career-kit/knowledge/ 目录
（含 scraper 自动写入的 JD/面经 + 用户手动放入的资料；路径常量见 paths.KNOWLEDGE_DIR）。
不做任何网络请求，不调用 LLM——没有数据时诚实告知，
并引导使用 fetch_company_jobs 获取实时数据。
"""

from __future__ import annotations

from typing import Any

from ..paths import KNOWLEDGE_DIR

SUPPORTED_EXTENSIONS = {".md", ".txt", ".json"}

# 通用搜索词——提取关键词时跳过
_STOP_WORDS = frozenset({
    "jd", "要求", "必备", "技能", "简历", "模板", "筛选", "标准",
    "关键词", "面试", "经验", "面经", "薪资", "趋势", "市场",
    "岗位", "职位", "描述", "分析", "参考", "案例", "同背景",
    "前辈", "候选", "画像", "准备", "通过",
})

# 公司别名 → 知识库目录名
_COMPANY_ALIASES = {
    "字节": "bytedance",
    "bytedance": "bytedance",
    "字节跳动": "bytedance",
    "boss": "boss",
    "boss直聘": "boss",
    "牛客": "nowcoder",
    "nowcoder": "nowcoder",
}


def _query_token_specs(query: str) -> list[dict]:
    """查询 → 加权 token 规格（text / weight / filename_ok）。

    - 短词（2-3 字）是可靠整词：正常计分，命中文件名 +2.0；
    - 长串（中文无空格，只能靠字面）：整串本身作为「整词」正常计分；
      另产出 2-gram 兜底召回，但 2-gram 噪声大——降权 0.05 且不参与文件名加分。
    复测 BUG：无意义长查询曾靠零散 2-gram 堆到 3.9 分混过阈值，降权后
    废词查询总分 < 1.2，被 MIN_RELEVANCE 挡住。
    """
    import re

    specs: dict[str, dict] = {}

    def _add(text: str, weight: float, filename_ok: bool) -> None:
        text = text.strip().lower()
        if not text or text in _STOP_WORDS:
            return
        spec = specs.get(text)
        if spec is None:
            specs[text] = {"text": text, "weight": weight, "filename_ok": filename_ok}
            return
        spec["weight"] = max(spec["weight"], weight)
        spec["filename_ok"] = spec["filename_ok"] or filename_ok

    tokens = re.split(r"[\s,，。.、;；:：!！?？()（）\[\]【】]+", str(query).lower())
    for token in tokens:
        if not token:
            continue
        if len(token) <= 3:
            _add(token, 1.0, True)
            continue
        _add(token, 1.0, True)  # 整串命中
        for i in range(len(token) - 1):
            _add(token[i:i + 2], 0.05, False)  # 2-gram 兜底召回（低权重）

    if not specs:
        lowered = str(query).strip().lower()
        if len(lowered) >= 2:
            specs[lowered] = {"text": lowered, "weight": 1.0, "filename_ok": True}
    return list(specs.values())


# 相关度阈值——低于该分数的结果不返回（弱相关材料容易被 LLM 误当证据，
# 用数量凑结果比空结果危害更大）。短词/整串命中可累计到 2.0+；
# 2-gram 噪声降权后废词查询总分 < 1.2，不会越过阈值。
MIN_RELEVANCE = 2.0


def search_knowledge(query: str, limit: int = 5) -> dict[str, Any]:
    """检索本地知识库。

    Args:
        query: 搜索关键词（如 "AI Agent 面经"、"字节跳动 JD"）
        limit: 返回条数上限

    Returns:
        {"results": [...], "count": int, "knowledge_dir": str}
    """
    if not KNOWLEDGE_DIR.exists():
        return {"results": [], "count": 0, "knowledge_dir": str(KNOWLEDGE_DIR)}

    query_lower = query.lower()
    token_specs = _query_token_specs(query)

    results = []
    for file_path in KNOWLEDGE_DIR.rglob("*"):
        if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue

        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception:
            continue

        rel_path = file_path.relative_to(KNOWLEDGE_DIR).as_posix()
        content_lower = content.lower()
        filename_lower = file_path.name.lower()

        score = 0.0
        for spec in token_specs:
            count = content_lower.count(spec["text"])
            if count:
                score += min(count * 0.1, 1.0) * spec["weight"]
            if spec["filename_ok"] and spec["text"] in filename_lower:
                score += 2.0
        if len(query_lower) >= 2 and query_lower in content_lower:
            score += 1.0

        if score > 0:
            results.append({
                "source": rel_path,
                "content": content[:2000],
                "relevance": round(score, 2),
            })

    results.sort(key=lambda x: x["relevance"], reverse=True)
    filtered = [r for r in results if r["relevance"] >= MIN_RELEVANCE]
    dropped = len(results) - len(filtered)
    return {
        "results": filtered[:limit],
        "count": len(filtered),  # 真实命中数，而非截断后的条数（显示「找到 N 条」时不能骗人）
        "weakest_dropped": dropped,  # 低分被截的条数（供上层如实提示「还有 N 条弱相关未返回」）
        "knowledge_dir": str(KNOWLEDGE_DIR),
    }
