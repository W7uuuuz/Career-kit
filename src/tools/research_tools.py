"""市场调研 MCP 工具——建档后的独立一步：批量抓取真实 JD 与同学学历经历。

research_market 返回方法论与 4 步执行模板；gather_research_data 一次完成
多源抓取（目标 1 家 + 对照 2-4 家 + 同学历案例），报告由代码渲染落盘到
用户资产目录（~/CareerKit），并写入 profile.research 供差距分析引用。

红线：报告内容不经 LLM 之手（来源真实的硬保证）；源失败如实上报，绝不编造。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any

from ..case_search import collect_cases
from ..guidance import login_action
from ..mcp_app import mcp
from ..research_digest import render_digest_lines
from ..research_report import _source_final_states, build_report, save_report
from ..scrapers.boss.auth import has_valid_cookies as boss_has_valid_cookies
from ..scrapers.loader import (
    get_job_detail,
    resolve_company,
    search_company_jobs,
)
from . import profile as profile_store
from .errors import InvalidJsonError, error_response
from .methodology import build_methodology_context
from .profile import load_profile
from .tool_helpers import _json

_MAX_SPECS = 6
_CASE_DEFAULT_LIMIT = 12
_ROSTER_MAX = 15
_ROSTER_CASE_MAX = 8
_BRIEF_LIMIT = 60
_DETAIL_MAX_IDS = 10
_DETAIL_TEXT_LIMIT = 6000
_SOURCE_TIMEOUT = 25.0
_SOURCE_RETRY = 1
_CASE_TIMEOUT = 30.0
_CASE_CONTENT_TIMEOUT = 20.0
_CASE_CONTENT_MAX = 8
_TOTAL_BUDGET = 50.0
_MAX_SOURCE_CONCURRENCY = 4
_PARTIAL_CACHE_TTL = 3600
_PARTIAL_CACHE_VERSION = 1
_CACHE_LOCK = threading.Lock()

_SOURCE_TIMEOUT_ENV = "CAREER_KIT_RESEARCH_SOURCE_TIMEOUT"



@mcp.tool()
def research_market() -> str:
    """市场调研：建档后的独立一步——批量抓取真实 JD 与同学学历经历。

    何时调用：finalize_profile 之后、analyze_gaps 之前（推荐顺序，
    差距分析会直接引用调研数据；无调研时分析只是软提示）。

    产出：调研报告（md 可读 / json 原始数据）落盘到
    用户资产目录（~/CareerKit/<档案>/调研报告/），报告内容 100% 来自真实
    抓取数据、每条带来源链接——这是 Career Kit 的核心卖点「来源真实」。

    Returns:
        方法论与 4 步模板；随后调用 gather_research_data 执行一次抓取。
    """
    profile = load_profile()
    ctx = build_methodology_context("market_research", profile)

    existing = profile.research or {}
    prior = None
    if existing.get("report_md"):
        prior = {
            "generated_at": existing.get("generated_at"),
            "report_md": existing.get("report_md"),
            "counts": existing.get("counts") or {},
            "note": "档案已有调研报告：差距分析会直接引用；重跑会生成新报告（各自留档）",
        }

    step_template = [
        {
            "step": 1,
            "name": "范围宣告",
            "action": "从 want/target_jd/who 提取目标方向、目标公司、城市、学历档，"
                      "向用户播报调研菜单：抓哪家（目标 1 + 对照 2-4 家）、约半分钟、"
                      "报告会存到用户资产目录——给用户随时喊停/增减的机会，不必等确认。"
                      "名单里若要放 BOSS 直聘，必须先单独问一句「是否抓取 BOSS 直聘"
                      "（我可以直接帮你打开登录窗口扫码）」，用户点头才加入并带 "
                      "boss_confirmed=true；用户拒绝就换成其他源，不得静默跳过",
            "output": {"menu": "目标方向 + 抓取名单 + 预计耗时 + 产出位置"},
            "checkpoint": False,
            "checkpoint_note": "宣告即执行；用户喊停才停；BOSS 源例外——必须先问用户",
        },
        {
            "step": 2,
            "name": "批量抓取",
            "action": "调用 gather_research_data(jd_specs, case_query, boss_confirmed) 一次完成："
                      "jd_specs 目标公司 1 条 + 对照 2-4 条（优先同城）；"
                      "实习方向优先 shixiseng（大厂/中厂实习覆盖、日薪、每周天数、实习月数、转正机会），"
                      "BOSS 只作薪资/广度补充，不作为实习主参考；"
                      "case_query 带 role/education（五档四层写法如「双非本」）/company/city。"
                      "含 BOSS 源时必须先问过用户并传 boss_confirmed=true——否则工具会"
                      "返回 CONFIRMATION_REQUIRED 让你去问；确认后按 "
                      "boss_login(action=\"status\") → 未就绪直接 boss_login(action=\"login\") → "
                      "登录成功后再调用 gather_research_data，不要先跑批再补登录；"
                      "若工具返回 ACTION_REQUIRED / LOGIN_REQUIRED，直接调用 "
                      "boss_login(action=\"login\")，不要再问第二次是否登录。"
                      "登录成功后窗口常驻、切成功页、不自动关闭，命令仅作兜底。"
                      "抓取阶段会逐条补抓岗位详情；未取得正文的岗位将被剔除。"
                      "BOSS 例外：研究阶段默认 list-only，保留薪资行、不补详情。"
                      "因此耗时主要来自其他来源的详情补抓；"
                      "调用前按源数量播报耗时：每源约 10-20 秒，总预算约 50 秒，另加逐条详情补抓；"
                      "源较多时建议拆成两批（目标 1 家 + 对照 2-4 家）",
            "output": {
                "report_paths": {"md": "", "json": ""},
                "source_status": [],
            },
            "checkpoint": False,
            "checkpoint_note": "任一源失败不中断，失败原因会如实进报告",
        },
        {
            "step": 3,
            "name": "报告落地",
            "action": "抓取完成后报告立即落盘（代码渲染，不经 LLM）。工具返回"
                      "「花名册（标识与摘要）+ 聚合摘要」，岗位全文不进入上下文。"
                      "向用户汇报三要素：样本构成（岗位/案例/各来源成败）→ 报告路径"
                      "（在控制台中查看，或双击桌面「Career Kit」快捷方式）→ 每条附来源链接可逐条核验",
            "output": {"summary_lines": 0, "path_shown": True, "gaps_reported": 0},
            "checkpoint": False,
            "checkpoint_note": "报告不阻塞查看；缺口如实陈述",
        },
        {
            "step": 4,
            "name": "衔接分析",
            "action": "按需读取全文：从花名册中选择 3-5 条，调用 "
                      "read_research_details(ids=...)，岗位用 kind=\"jd\"，"
                      "面经与他人路径用 kind=\"case\"；宿主 harness 支持子 Agent 时，"
                      "由父 Agent 用 Task 发起 research-analyst（仓库已提供定义）："
                      "把花名册、聚合摘要与 delegate.prompt 交给它，由它自行筛选、分批读取"
                      "并返回分析结论与重点名单，父 Agent 仅汇总结论。"
                      "随后进入差距分析（第 3 步），差距分析将直接引用本次调研数据；"
                      "用户可先阅读报告，确认后进入分析",
            "output": "用户确认后进入 analyze_gaps 流程",
            "checkpoint": True,
            "checkpoint_note": "等用户确认后再开始分析",
        },
    ]

    instructions = (
        "步骤预告：先向用户报 4 步菜单（①范围宣告 ②批量抓取 ③报告落地 ④衔接分析），"
        "报完再执行。\n"
        "BOSS 源纪律：名单含 BOSS 直聘时，抓取前只问一次「是否把 BOSS 加入调研"
        "（如需登录我会直接打开登录窗口，你只需扫码）」——同意后传 boss_confirmed=true；"
        "不同意则更换来源，不得静默跳过。若返回 CONFIRMATION_REQUIRED 才问用户；"
        "返回 ACTION_REQUIRED / next_tool=boss_login 时直接调用 "
        "boss_login(action=\"login\")，不要再问第二次是否登录，"
        "也不得自行判定调研失败。顺序：boss_login(status) → 未就绪 login → "
        "再 gather_research_data；不要先跑批再补登录。\n"
        "实习源优先级：目标是实习（尤其是大厂/中厂实习）时，优先用 shixiseng"
        "（keyword=方向或公司名，city 限制，日薪/每周天数/实习月数/转正机会都可核验）；"
        "BOSS 用于补充薪资与广度，不作为实习主参考；指定公司的岗位要求在官网 JD 里核对。\n"
        "详情纪律：工具为每条岗位补抓正文；未取得详情的岗位将被剔除并计入数据缺口。"
        "BOSS 研究阶段默认 list-only：不补详情、不剔除，保留薪资行，"
        "数据缺口会写明「BOSS 仅列表数据，未抓 JD 详情」。"
        "汇报时须说明「已剔除 N 条未取得详情的岗位」，不得以标题代替完整 JD。\n"
        "花名册机制：gather 返回的花名册仅含标识与摘要，岗位/案例全文已写入报告与档案。"
        "读取全文须按 id 定向调用 read_research_details，单次建议 3-5 条；"
        "样本量较大时，若宿主 harness 支持子 Agent，用 Task 发起 research-analyst"
        "（仓库提供 .opencode/agent 与 .claude/agents 定义），把花名册、聚合摘要与"
        " delegate.prompt 交给它，父 Agent 仅汇总其结论与重点名单。\n"
        "播报纪律：调用 gather_research_data 前说明「抓取哪些来源 + 每源约 10-20 秒、"
        "总预算约 50 秒、详情逐条补抓；源较多时建议拆批」，不得静默执行。\n"
        "汇报口径：摘要须包含样本数与来源成败；路径展示工具返回的完整位置（不得编造）；"
        "明确说明「每条附来源链接可逐条核验；未获取的内容已标注未获取」。\n"
        "调研只采集事实，不做评价——解读留给差距分析，汇报中对数据的评述不超过一句。\n"
        "全部失败时如实告知（绝不编造），并引导用户以 import_jd / import_jd_file 补充材料。"
    )

    return _json(
        {
            "next_steps": ["gather_research_data", "analyze_gaps"],
            "methodology": ctx["methodology"],
            "profile": ctx["profile"],
            "prior_research": prior,
            "step_template": step_template,
            "instructions": instructions,
        }
    )


def _parse_specs(raw: str, field_name: str) -> Any:
    """解析 JSON 数组/对象字符串（带常见 LLM 包裹容错）。"""
    if isinstance(raw, (list, dict)):
        return raw
    text = str(raw).strip()
    if not text:
        return None
    candidates = [text]
    if "```" in text:
        candidates.extend(
            seg.strip()
            for seg in text.replace("```json", "```").split("```")
            if seg.strip() and seg.strip() not in candidates
        )
    errors: list[str] = []
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, TypeError) as exc:
            errors.append(str(exc))
            continue
        if isinstance(parsed, (list, dict)):
            return parsed
        errors.append(f"非数组/对象：{type(parsed).__name__}")
    raise InvalidJsonError(
        f"{field_name} 必须是 JSON 数组或对象，解析失败（已尝试原文/代码块）："
        "键用双引号，无尾逗号。",
        {"raw": text[:200], "attempts": errors[:3]},
    )


def _uses_boss(specs: list[dict[str, Any]], query: dict[str, Any]) -> bool:
    """调研范围是否包含 BOSS 直聘（jd_specs 或 case_query.company）。"""
    names = [str(spec.get("company") or "") for spec in specs]
    names.append(str(query.get("company") or ""))
    for name in names:
        cleaned = name.strip()
        if not cleaned:
            continue
        if resolve_company(cleaned) == "boss":
            return True
    return False


def _enrich_with_detail(
    slug: str, rows: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[str]]:
    """逐条补抓岗位详情；拿不到正文的岗位剔除（无详情岗位无调研价值）。

    BOSS 的列表行带 ``detail_status="list_only"``：研究阶段保留薪资与公司/地点/
    技能标签，不补详情、也不剔除；需要全文时由 fetch_jd_detail 交互式补抓。

    Returns:
        (保留的岗位行, 被剔除的岗位标题)
    """
    kept: list[dict[str, Any]] = []
    dropped: list[str] = []
    for row in rows:
        if str(row.get("detail_status") or "") == "list_only":
            kept.append(dict(row))
            continue
        url = str(row.get("url") or "").strip()
        detail: dict[str, Any] = {}
        if url:
            try:
                detail = get_job_detail(url, company=slug) or {}
            except Exception as exc:  # noqa: BLE001 - 单条失败不影响整体
                detail = {"error": f"{type(exc).__name__}: {exc}"}
        description = str(
            detail.get("description") or detail.get("content") or ""
        ).strip()
        requirements = str(detail.get("requirements") or "").strip()
        if detail.get("error") or not (description or requirements):
            dropped.append(str(row.get("title") or url or "未知岗位"))
            continue
        enriched = dict(row)
        enriched["description"] = description
        enriched["requirements"] = requirements
        for field in (
            "degree", "education", "weekly_days", "duration_months", "chance",
            "salary", "location", "company", "skills", "tags",
        ):
            if not enriched.get(field) and detail.get(field):
                enriched[field] = detail[field]
        enriched["detail_status"] = "ok"
        kept.append(enriched)
    return kept, dropped


def _partial_cache_path() -> Path:
    return Path(profile_store.PROFILE_DIR) / "cache" / "research_partial.json"


def _research_fingerprint(
    specs: list[dict[str, Any]], query: dict[str, Any], direction: str
) -> str:
    payload = json.dumps(
        {"specs": specs, "query": query, "direction": direction},
        ensure_ascii=False, sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def _research_round_key(
    direction: str, city: str, education: str, profile_name: str
) -> str:
    """同一轮调研的稳定标识：方向 + 城市 + 教育档 + 档案名（不含 specs）。

    分批抓取时 specs 不同，但同方向/城市/教育档/档案属于同一轮，
    由 save_report 在时间窗口内复用同一份报告文件。
    """
    payload = json.dumps(
        {
            "direction": direction.strip().lower(),
            "city": city.strip().lower(),
            "education": education.strip().lower(),
            "profile": profile_name.strip().lower(),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def _read_partial_cache(fingerprint: str) -> dict[str, Any]:
    path = _partial_cache_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    if data.get("version") != _PARTIAL_CACHE_VERSION:
        return {}
    if data.get("fingerprint") != fingerprint:
        return {}
    if time.time() - float(data.get("saved_at") or 0) > _PARTIAL_CACHE_TTL:
        return {}
    entries = data.get("entries")
    return entries if isinstance(entries, dict) else {}


def _write_partial_cache(
    fingerprint: str, key: str, value: dict[str, Any]
) -> None:
    """单源完成即落盘；超时后线程继续跑完也能被下一次调用复用。"""
    path = _partial_cache_path()
    with _CACHE_LOCK:
        entries = _read_partial_cache(fingerprint)
        entries[key] = value
        payload = {
            "version": _PARTIAL_CACHE_VERSION,
            "fingerprint": fingerprint,
            "saved_at": time.time(),
            "entries": entries,
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            )
            tmp.replace(path)
        except OSError:
            pass


def _clear_partial_cache(fingerprint: str) -> None:
    with _CACHE_LOCK:
        path = _partial_cache_path()
        try:
            if _read_partial_cache(fingerprint):
                path.unlink(missing_ok=True)
        except OSError:
            pass


def _family_cache_key(slug: str, raw_spec: dict[str, Any]) -> str:
    payload = json.dumps({"slug": slug, "spec": raw_spec}, sort_keys=True)
    return "jd:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


_KEYWORD_ALIASES: dict[str, tuple[str, ...]] = {
    "agent": ("agent", "智能体"),
    "智能体": ("智能体", "agent"),
    "ai": ("ai", "人工智能"),
    "人工智能": ("人工智能", "ai"),
    "llm": ("llm", "大模型", "大语言模型"),
    "大模型": ("大模型", "大语言模型", "llm"),
    "大语言模型": ("大语言模型", "大模型", "llm"),
    "rag": ("rag", "检索增强"),
    "检索增强": ("检索增强", "rag"),
    "开发": ("开发", "研发", "工程师"),
    "研发": ("研发", "开发", "工程师"),
}

_KEYWORD_TOKEN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]+", re.I)


def _keyword_groups(phrase: str) -> list[tuple[str, ...]]:
    """把查询词切成英文/中文 token，并展开常见同义词。"""
    tokens = [
        token
        for token in _KEYWORD_TOKEN_RE.findall(phrase)
        if len(token) >= 2 or token.isdigit()
    ]
    groups: list[tuple[str, ...]] = []
    for token in tokens:
        lowered = token.lower()
        aliases = _KEYWORD_ALIASES.get(lowered, (lowered,))
        if lowered not in aliases:
            aliases = (lowered, *aliases)
        groups.append(tuple(dict.fromkeys(aliases)))
    return groups


def _filter_relevant_rows_traced(
    rows: list[dict[str, Any]], keyword: str
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """按关键词过滤跑偏岗位，同时保留被过滤样本供复核（不静默丢弃）。"""
    phrase = str(keyword or "").strip().lower()
    if not rows:
        return rows, []
    groups = _keyword_groups(phrase)
    threshold = max(1, math.ceil(len(groups) * 0.6)) if groups else 1
    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, str]] = []
    for row in rows:
        if row.get("title_quality") == "low":
            dropped.append(
                {
                    "title": str(row.get("title") or row.get("url") or "未命名岗位"),
                    "reason": "标题解析质量低（自定义字体未完全还原）",
                    "url": str(row.get("url") or ""),
                }
            )
            continue
        text = " ".join(
            str(row.get(key) or "")
            for key in ("title", "summary", "description", "requirements")
        ).lower()
        if not phrase:
            kept.append(row)
            continue
        hit_terms = [alts[0] for alts in groups if any(alias in text for alias in alts)]
        if phrase in text or len(hit_terms) >= threshold:
            kept.append(row)
        else:
            dropped.append(
                {
                    "title": str(row.get("title") or row.get("url") or "未命名岗位"),
                    "reason": (
                        f"未命中查询关键词「{keyword}」"
                        + (f"（分词命中 {len(hit_terms)}/{len(groups)}）" if groups else "")
                    ),
                    "url": str(row.get("url") or ""),
                }
            )
    return kept, dropped


def _filter_relevant_rows(
    rows: list[dict[str, Any]], keyword: str
) -> list[dict[str, Any]]:
    """按关键词过滤跑偏岗位，避免「AI-HR 培训生」混进 Agent 开发调研。

    规则：完整关键词命中，或至少命中 2 个分词（单关键词必须命中）。
    只过滤搜索接口返回的列表，不改变详情数据。
    """
    kept, _ = _filter_relevant_rows_traced(rows, keyword)
    return kept


def _resolve_source_timeout(override: float = 0.0) -> float:
    """单源超时可配置：显式入参 > 环境变量 > 默认 25 秒。"""
    if override and override > 0:
        return float(override)
    try:
        env_value = float(os.environ.get(_SOURCE_TIMEOUT_ENV, "") or 0)
    except ValueError:
        env_value = 0.0
    return env_value if env_value > 0 else _SOURCE_TIMEOUT


def _fetch_family_sync(
    slug: str,
    label: str,
    raw_spec: dict[str, Any],
    cache_key: str,
    fingerprint: str,
) -> dict[str, Any]:
    """抓取单个 JD 源并补详情；成功/空结果立即写断点缓存。"""
    t0 = time.perf_counter()
    try:
        resp = search_company_jobs(slug, **raw_spec)
    except Exception as exc:  # noqa: BLE001 - 单源失败不拖垮整批
        resp = {"error": f"{type(exc).__name__}: {exc}", "results": []}
    elapsed = time.perf_counter() - t0
    rows = resp.get("results") or []
    raw_count = len(rows)
    rows, filtered_samples = _filter_relevant_rows_traced(
        rows, str(raw_spec.get("keyword") or "")
    )
    filtered_out = raw_count - len(rows)
    if resp.get("error") and not rows:
        return {
            "slug": slug, "label": label or slug, "rows": [], "status": "failed",
            "error": str(resp["error"]), "elapsed": elapsed,
            "dropped_no_detail": 0, "dropped_titles": [],
            "filtered_irrelevant": filtered_out,
            "filtered_titles": [
                item.get("title", "") for item in filtered_samples
            ],
            "filtered_samples": filtered_samples,
        }
    dropped: list[str] = []
    if rows:
        rows, dropped = _enrich_with_detail(slug, rows)
    list_only = sum(
        1 for row in rows if str(row.get("detail_status") or "") == "list_only"
    )
    family = {
        "slug": slug, "label": label or slug, "rows": rows,
        "status": "ok" if rows else "empty", "error": "",
        "elapsed": elapsed,
        "dropped_no_detail": len(dropped),
        "dropped_titles": dropped[:5],
        "filtered_irrelevant": filtered_out,
        "filtered_titles": [
            item.get("title", "") for item in filtered_samples[:10]
        ],
        "filtered_samples": filtered_samples[:10],
        "list_only": list_only,
        "attempts": 1,
        "retried": False,
    }
    if family["status"] in ("ok", "empty"):
        _write_partial_cache(fingerprint, cache_key, family)
    return family


def _one_line(text: Any) -> str:
    return " ".join(str(text or "").split())


def _cases_cache_key(query: dict[str, Any], role: str) -> str:
    """案例断点键：来源聚合 + 查询条件，重跑同一查询才复用。"""
    payload = json.dumps(
        {
            "role": role,
            "company": query.get("company") or "",
            "city": query.get("city") or "",
            "education": query.get("education") or "",
            "kind": query.get("kind") or "both",
            "limit": query.get("limit") or _CASE_DEFAULT_LIMIT,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return "cases:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _case_content_from_local(path_text: str) -> str:
    path = Path(path_text)
    if not path.exists():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if path.suffix.lower() == ".json":
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            data = None
        if isinstance(data, dict):
            parts = [
                str(data.get(key)).strip()
                for key in (
                    "title", "company", "location", "summary",
                    "description", "requirements", "content",
                )
                if str(data.get(key) or "").strip()
            ]
            if parts:
                text = "\n".join(parts)
    return text.strip()


def _case_needs_remote_content(case: dict[str, Any]) -> bool:
    if case.get("category") == "jd" or case.get("origin") == "local_jd":
        return False
    url = str(case.get("url") or "").strip().lower()
    if not url.startswith(("http://", "https://")):
        return False
    source = str(case.get("source") or "").lower()
    return (
        source in {"nowcoder", "github"}
        or "nowcoder.com" in url
        or "github.com" in url
    )


def _summarize_case_contents(result: dict[str, Any]) -> dict[str, Any]:
    cases = [case for case in (result.get("cases") or []) if isinstance(case, dict)]
    ok = sum(1 for case in cases if case.get("content_status") == "ok")
    unavailable = [
        case for case in cases if case.get("content_status") == "unavailable"
    ]
    result["case_content_status"] = {
        "ok": ok,
        "unavailable": len(unavailable),
        "total": len(cases),
    }
    if unavailable:
        titles = "、".join(
            str(case.get("title") or "未命名")[:40] for case in unavailable[:5]
        )
        warnings = result.setdefault("warnings", [])
        warnings.append(
            f"cases: {len(unavailable)} 条面经未抓到全文（{titles}），"
            "可点原文链接或用 fetch_jd_detail 补全文"
        )
    return result


def _attach_case_contents(result: dict[str, Any]) -> dict[str, Any]:
    """调研时把面经/案例全文落盘到结果里，读取时零网络请求。"""
    cases = result.get("cases") or []
    fetched = 0
    for case in cases:
        if not isinstance(case, dict):
            continue
        if str(case.get("content") or "").strip():
            case["content_status"] = "ok"
            continue
        local_path = str(case.get("local_path") or "").strip()
        if local_path:
            content = _case_content_from_local(local_path)
            if content:
                case["content"] = content
                case["content_status"] = "ok"
                case["content_source"] = "local"
                continue
        if fetched >= _CASE_CONTENT_MAX or not _case_needs_remote_content(case):
            case["content_status"] = "unavailable"
            case.setdefault(
                "content_error", "调研时未抓取全文（仅保留来源链接与要点）"
            )
            continue
        fetched += 1
        try:
            detail = get_job_detail(str(case.get("url") or "")) or {}
        except Exception as exc:  # noqa: BLE001 - 单条失败不拖垮案例
            detail = {"error": f"{type(exc).__name__}: {exc}"}
        content = str(
            detail.get("content") or detail.get("description")
            or detail.get("requirements") or ""
        ).strip()
        if content and not detail.get("error"):
            case["content"] = content
            case["content_status"] = "ok"
            case["content_source"] = "fetched"
        else:
            case["content_status"] = "unavailable"
            case["content_error"] = _one_line(
                detail.get("error") or "详情接口未返回全文"
            )
    return _summarize_case_contents(result)


async def _run_research(
    profile: Any,
    specs: list[dict[str, Any]],
    query: dict[str, Any],
    direction: str,
    city: str,
    role: str,
    fingerprint: str,
    cache_entries: dict[str, Any],
    source_timeout: float = 0.0,
) -> dict[str, Any]:

    families: list[dict[str, Any] | None] = [None] * len(specs)
    resumed = 0
    incomplete = False
    deadline = time.perf_counter() + _TOTAL_BUDGET
    semaphore = asyncio.Semaphore(_MAX_SOURCE_CONCURRENCY)
    per_source_timeout = _resolve_source_timeout(source_timeout)

    async def run_spec(index: int, spec: dict[str, Any]) -> None:
        nonlocal resumed, incomplete
        raw_spec = dict(spec)
        raw_name = str(raw_spec.pop("company", "") or "")
        label = str(raw_spec.pop("label", "") or raw_name)
        # jd_specs 往往只写 company，关键词实际在 case_query.role；
        # 未显式给 keyword 时用 role 补上，缓存键/抓取/相关性过滤口径一致。
        if not raw_spec.get("keyword") and role:
            raw_spec["keyword"] = role
        if not raw_name:
            families[index] = {
                "slug": "", "label": label or "无效配置", "rows": [],
                "status": "failed", "error": "spec 缺少 company 字段", "elapsed": 0.0,
            }
            incomplete = True
            return
        slug = resolve_company(raw_name)
        cache_key = _family_cache_key(slug, raw_spec)
        cached = cache_entries.get(cache_key)
        if isinstance(cached, dict) and cached.get("status") in ("ok", "empty"):
            family = dict(cached)
            family["from_cache"] = True
            families[index] = family
            resumed += 1
            return

        async with semaphore:
            attempts = 0
            family: dict[str, Any] | None = None
            while attempts <= _SOURCE_RETRY:
                remaining = deadline - time.perf_counter()
                if remaining <= 2:
                    family = {
                        "slug": slug, "label": label or slug, "rows": [], "status": "failed",
                        "error": "本次总时长预算已用完，该源未抓取；已完成来源已落盘，重跑会续抓",
                        "elapsed": 0.0, "dropped_no_detail": 0, "dropped_titles": [],
                        "attempts": max(attempts, 1), "retried": attempts > 1,
                    }
                    incomplete = True
                    break
                if attempts:
                    refreshed = _read_partial_cache(fingerprint).get(cache_key)
                    if isinstance(refreshed, dict) and refreshed.get("status") in (
                        "ok", "empty",
                    ):
                        family = dict(refreshed)
                        family["from_cache"] = True
                        resumed += 1
                        break
                attempts += 1
                timeout = min(per_source_timeout, remaining)
                try:
                    family = await asyncio.wait_for(
                        asyncio.to_thread(
                            _fetch_family_sync, slug, label, raw_spec, cache_key, fingerprint
                        ),
                        timeout=timeout,
                    )
                except TimeoutError:
                    family = {
                        "slug": slug, "label": label or slug, "rows": [], "status": "failed",
                        "error": f"单源超时（超过 {timeout:.0f} 秒），已跳过；其他源继续，"
                                 "重跑会从断点续抓",
                        "elapsed": timeout, "dropped_no_detail": 0, "dropped_titles": [],
                        "filtered_irrelevant": 0, "filtered_samples": [],
                    }
                except Exception as exc:  # noqa: BLE001 - 单源异常不拖垮整批
                    family = {
                        "slug": slug, "label": label or slug, "rows": [], "status": "failed",
                        "error": f"{type(exc).__name__}: {exc}", "elapsed": 0.0,
                        "dropped_no_detail": 0, "dropped_titles": [],
                        "filtered_irrelevant": 0, "filtered_samples": [],
                    }
                if family.get("status") != "failed":
                    break
            if family is None:
                family = {
                    "slug": slug, "label": label or slug, "rows": [], "status": "failed",
                    "error": "该源未完成抓取", "elapsed": 0.0,
                    "dropped_no_detail": 0, "dropped_titles": [],
                }
            family["attempts"] = max(int(family.get("attempts") or 1), attempts)
            family["retried"] = bool(family.get("retried") or attempts > 1)
            if family.get("status") == "failed":
                incomplete = True
            families[index] = family

    async def run_cases() -> dict[str, Any]:
        nonlocal resumed, incomplete
        if not role:
            return {"cases": [], "warnings": [], "sources": {}}
        case_company = str(query.get("company") or "")
        cases_key = _cases_cache_key(query, role)
        cached_cases = cache_entries.get(cases_key)
        if isinstance(cached_cases, dict) and cached_cases.get("cases"):
            resumed += 1
            return dict(cached_cases)
        remaining = deadline - time.perf_counter()
        if remaining <= 2:
            incomplete = True
            return {
                "cases": [], "sources": {},
                "warnings": ["cases: 本次总时长预算已用完，案例未抓取；可重跑续抓"],
            }
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    collect_cases,
                    role=role,
                    company=case_company,
                    city=str(query.get("city") or ""),
                    education=str(query.get("education") or ""),
                    kind=str(query.get("kind") or "both"),
                    limit=int(query.get("limit") or _CASE_DEFAULT_LIMIT),
                ),
                timeout=min(_CASE_TIMEOUT, remaining),
            )
        except TimeoutError:
            incomplete = True
            return {
                "cases": [], "sources": {},
                "warnings": [f"cases: 案例抓取超时（超过 {_CASE_TIMEOUT:.0f} 秒），已跳过"],
            }
        except Exception as exc:  # noqa: BLE001 - 案例异常不拖垮整批
            incomplete = True
            return {
                "cases": [], "sources": {},
                "warnings": [f"cases: {type(exc).__name__}: {exc}"],
            }
        _write_partial_cache(fingerprint, cases_key, result)
        remaining = deadline - time.perf_counter()
        if remaining > 2:
            try:
                result = await asyncio.wait_for(
                    asyncio.to_thread(_attach_case_contents, result),
                    timeout=min(_CASE_CONTENT_TIMEOUT, remaining),
                )
            except TimeoutError:
                for case in result.get("cases") or []:
                    if isinstance(case, dict) and not str(case.get("content") or "").strip():
                        case["content_status"] = "unavailable"
                        case["content_error"] = "案例全文抓取超时，未落盘"
                result = _summarize_case_contents(result)
            _write_partial_cache(fingerprint, cases_key, result)
        return result

    # 案例与 JD 源并行：避免 JD 源吃满预算后案例直接为 0（复测 BUG #5）。
    # 用 gather 统一调度：外部取消时会一并取消子任务，不留下孤儿任务。
    results = await asyncio.gather(
        run_cases(),
        *(run_spec(index, spec) for index, spec in enumerate(specs)),
    )
    cases_result = results[0]

    want = profile.want or {}
    who = profile.who or {}
    direction_value = (direction or role or str(want.get("target_role") or "")).strip()
    city_value = (
        city
        or str(query.get("city") or "")
        or str(want.get("city") or who.get("city") or "")
    ).strip()
    education_value = str(
        query.get("education") or who.get("education") or ""
    ).strip()
    return {
        "direction": direction_value or "市场调研",
        "city": city_value,
        "education_tag": education_value,
        "jd_families": [f for f in families if f is not None],
        "cases_result": cases_result,
        "partial": {
            "incomplete": incomplete,
            "resumed_sources": resumed,
            "cache_path": str(_partial_cache_path()),
            "budget_seconds": _TOTAL_BUDGET,
        },
    }


@mcp.tool()
async def gather_research_data(
    jd_specs: str = "",
    case_query: str = "",
    direction: str = "",
    city: str = "",
    boss_confirmed: bool = False,
    source_timeout: float = 0.0,
) -> str:
    """批量抓取真实市场数据并生成调研报告（调研步核心动作，一次调用完成）。

    Args:
        jd_specs: JD 抓取范围 JSON 数组，目标 1 家 + 对照 2-4 家，如
            [{"company": "字节", "limit": 6}, {"company": "boss", "city": "北京", "limit": 6}]；
            company 支持别名（字节/boss/官方源id），其余键原样透传给对应源（city/keyword/limit…）
        case_query: 同学历案例查询 JSON 对象，如
            {"role": "AI Agent 开发", "education": "双非本", "company": "字节", "kind": "both"}
            ——education 用五档四层写法（985/211/双非/专科 × 博/硕/本/专）
        direction: 报告标题与档案归档使用的方向名（默认取 case_query.role）
        city: 报告上下文城市（默认取 case_query.city / want / who）
        boss_confirmed: 范围含 BOSS 直聘时必须先问用户，用户同意后传 true。
             「是否抓 BOSS」与「是否扫码登录」合并为一次同意：未确认返回
             CONFIRMATION_REQUIRED；确认但未登录返回 ACTION_REQUIRED
             （next_tool=boss_login），不再追问第二次。用户同意后直接调用
             boss_login(action="login")（用户只需扫码），登录成功后浏览器保持常开。
        source_timeout: 单源超时秒数（默认 25，也可用环境变量
             CAREER_KIT_RESEARCH_SOURCE_TIMEOUT 配置）；单源失败会自动重试 1 次。

    Returns:
        汇报文本：样本统计 + 来源成功/失败 + 报告完整路径（控制台入口） +
        数据缺口 + 下一步衔接分析。报告内容 100% 代码渲染自抓取数据（不经 LLM）。

    纪律：
    - 详情必抓：每条岗位抓取正文（description/requirements）；无详情岗位直接剔除，
      剔除数量进来源面板与数据缺口（没有详情的岗位对调研没有价值）
    - BOSS 例外：detail_status=list_only 的行保留薪资/公司/地点/技能，不补详情不剔除；
      list_only 数量进来源面板、counts 与数据缺口，需要全文时用 fetch_jd_detail 补抓
    - 任一源失败不中断；失败原因进报告「来源状态面板」如实展示
    - BOSS 抓取前必须先问用户（boss_confirmed=true 才算确认）；含 BOSS 时先
      boss_login(action="status")，未就绪直接 boss_login(action="login")，登录成功后
      再调用 gather_research_data，不要先跑批再补登录；不再二次询问是否登录；
      登录成功后窗口常驻、切成功页、不自动关闭，命令仅作兜底
    - 全部失败时返回可读错误并引导 import_jd / import_jd_file，绝不编造
    """
    try:
        specs = _parse_specs(jd_specs, "jd_specs") or []
        query = _parse_specs(case_query, "case_query") or {}
    except InvalidJsonError as exc:
        return error_response("INVALID_JSON", exc.message, exc.details)
    if isinstance(specs, dict):
        specs = [specs]
    if not isinstance(specs, list) or not isinstance(query, dict):
        return error_response(
            "INVALID_JSON",
            "jd_specs 必须是 JSON 数组，case_query 必须是 JSON 对象",
            {
                "jd_specs_type": type(specs).__name__,
                "case_query_type": type(query).__name__,
            },
        )
    specs = [s for s in specs if isinstance(s, dict)][: _MAX_SPECS]
    role = str(query.get("role") or direction or "").strip()
    if not specs and not role:
        return error_response(
            "MISSING_DATA",
            "调研需要至少一项抓取范围：jd_specs（岗位对照）或 case_query.role（同学历案例）。",
            {
                "example": {
                    "jd_specs": [
                        {"company": "字节", "limit": 6},
                        {"company": "boss", "city": "北京", "limit": 6},
                    ],
                    "case_query": {"role": "AI Agent 开发", "education": "双非本"},
                }
            },
        )

    # BOSS 登录确认：抓取前先做一次轻量登录态探测，避免先跑完其他源才发现
    # BOSS 不可用（P2-9）。一次同意同时覆盖「抓 BOSS」与「扫码登录」。
    uses_boss = _uses_boss(specs, query)
    boss_unlogged = uses_boss and not boss_has_valid_cookies()
    if uses_boss and not boss_confirmed:
        return error_response(
            "CONFIRMATION_REQUIRED",
            "调研范围含 BOSS 直聘：同意抓取即可，若尚未登录我会打开登录窗口（可能需要扫码）；"
            "下一次调用直接复用同一会话。",
            {
                **login_action(f'"{sys.executable}" -m src.scrapers.boss.login'),
                "login_tool": "boss_login",
                "question": "是否把 BOSS 直聘加入本次调研？如需登录，我会直接打开登录窗口，你只需扫码。",
                "options": [
                    "同意：带 boss_confirmed=true 重新调用；若未登录先调用 boss_login(action=\"login\")",
                    "不同意：从 jd_specs / case_query 移除 boss 后重跑，其他源照常抓取",
                ],
                "rule": "只问一次；同意后直接调用 boss_login(action=\"login\")（未登录时），"
                        "不要再问第二个「是否现在登录」；不得静默跳过 BOSS 或直接宣布失败",
            },
        )

    if uses_boss and boss_unlogged:
        return error_response(
            "ACTION_REQUIRED",
            "BOSS 直聘已确认抓取但尚未登录：直接调用 boss_login(action=\"login\") 扫码，"
            "登录成功后浏览器保持常开，再带 boss_confirmed=true 重跑本工具。"
            "不需要再问用户是否登录。",
            {
                **login_action(f'"{sys.executable}" -m src.scrapers.boss.login'),
                "action": "boss_login",
                "reason": "not_logged_in",
                "next_tool": "boss_login",
                "resume": {
                    "boss_confirmed": True,
                    "jd_specs": specs,
                    "case_query": query,
                    "direction": direction,
                    "city": city,
                },
                "after_login": "登录完成后带 boss_confirmed=true 重新调用 gather_research_data",
                "alternative": "不想登录时，把 jd_specs / case_query 里的 boss 移除后重跑，其他源照常抓取",
                "resume_hint": "已完成来源会写入断点缓存，登录后重跑会自动续抓，不必从头再来",
                "rule": "用户已同意抓取 BOSS，直接调用 boss_login(action=\"login\")，"
                        "不要再问「是否现在登录」；不得把登录失败直接当调研失败宣布",
            },
        )

    profile = load_profile()

    fingerprint = _research_fingerprint(specs, query, direction)
    cache_entries = _read_partial_cache(fingerprint)

    gathered = await _run_research(
        profile, specs, query, direction, city, role, fingerprint, cache_entries,
        source_timeout=source_timeout,
    )
    report = build_report(profile, gathered)
    report["fingerprint"] = fingerprint
    report_context = report.get("context") or {}
    report["round_key"] = _research_round_key(
        str(report.get("direction") or report_context.get("goal") or ""),
        str(report.get("city") or report_context.get("city") or ""),
        str(report.get("education_tag") or report_context.get("education") or ""),
        profile_store.get_active_profile_name(),
    )
    counts = report.get("counts") or {}
    # 运行中可能被 API 环境异常主动销毁；重新读一次，不能只看抓取前状态
    boss_auth_lost = (
        uses_boss
        and not boss_unlogged
        and not boss_has_valid_cookies()
    )
    if not (counts.get("jd_samples") or counts.get("cases")):
        if boss_unlogged or boss_auth_lost:
            reason = (
                "BOSS 直聘登录态已过期或触发环境异常，已被销毁，"
                if boss_auth_lost
                else "BOSS 直聘未登录，"
            )
            return error_response(
                "LOGIN_REQUIRED",
                f"{reason}其他来源本次也没有可用数据。"
                "直接调用 boss_login(action=\"login\") 扫码后重试，或改用其他数据源/导入 JD。",
                {
                    **login_action(f'"{sys.executable}" -m src.scrapers.boss.login'),
                    "action": "boss_login",
                    "reason": "not_logged_in",
                    "next_tool": "boss_login",
                    "after_login": "登录完成后带 boss_confirmed=true 重新调用 gather_research_data",
                    "source_status": report.get("source_status") or [],
                    "rule": "用户已同意抓取 BOSS，直接调用 boss_login(action=\"login\")，"
                            "不要再问「是否现在登录」",
                },
            )
        return error_response(
            "MISSING_DATA",
            "调研未获取到任何数据——各源失败或无结果，已如实中止，未编造任何替代内容。",
            {
                "source_status": report.get("source_status") or [],
                "case_warnings": report.get("case_warnings") or [],
                "suggestion": (
                    "换关键词/城市重跑（例：jd_specs 增加 BOSS 源 + keyword），"
                    "或用 import_jd / import_jd_file 导入手头 JD"
                ),
                "partial_cache": str(_partial_cache_path()),
                "resume_hint": "已完成的来源会写入断点缓存；重跑同一范围会自动续抓",
            },
        )

    paths = await asyncio.to_thread(save_report, profile, report)
    # Core v2 同步：调研报告落盘后写 MarketBaseline artifact（失败不阻断）
    try:
        from ..core.sync import sync_market_baseline

        sync_market_baseline(profile_store.get_active_profile_name())
    except Exception:  # noqa: BLE001 - sync 失败不阻断主工具
        pass
    message = _render_report_message(report, paths)
    partial_info = gathered.get("partial") or {}
    if partial_info.get("incomplete"):
        message += (
            "\n\n本次有来源未完成（单源超时/失败或总时长预算用完）："
            f"已完成的来源已落盘到断点缓存（{partial_info.get('cache_path')}）；"
            "重跑同一范围会自动续抓，不必从头再来。"
        )
    else:
        _clear_partial_cache(fingerprint)
    actual_families = [
        item for item in (gathered.get("jd_families") or []) if item.get("slug")
    ]
    actual_source_count = len(actual_families) + (1 if role else 0)
    if actual_source_count > 2:
        message += (
            f"\n\n本轮源较多（{actual_source_count} 个），已在 {_TOTAL_BUDGET:.0f} 秒预算内返回；"
            "未完成来源已写断点缓存，重跑会续抓；下次建议拆批。"
        )
    if boss_auth_lost:
        message += (
            "\n\nBOSS 直聘：登录态已过期或触发环境异常，已被销毁。"
            "需要补全时直接调用 boss_login(action=\"login\")（用户只需扫码），"
            "登录成功后浏览器保持常开，再带 boss_confirmed=true 重跑。"
        )
    return message


def _brief(text: Any, limit: int = _BRIEF_LIMIT) -> str:
    """花名册摘要：单行截断，仅用于筛选。"""
    s = " ".join(str(text or "").split())
    if len(s) <= limit:
        return s
    return s[: limit - 1] + "…"


def _parse_id_list(raw: Any) -> list[str]:
    """解析 id 列表：支持 JSON 数组 / 逗号 / 空格 / 顿号。"""
    if isinstance(raw, (list, tuple)):
        return [str(item).strip() for item in raw if str(item).strip()]
    text = str(raw or "").strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            parsed = None
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    return [part for part in re.split(r"[,，、\s]+", text.strip("[]\"'")) if part]


def _cap_text(text: Any, limit: int = _DETAIL_TEXT_LIMIT) -> tuple[str, bool]:
    """全文上限保护：超限时截断并标记（正常 JD 不应触发）。"""
    s = str(text or "").strip()
    if len(s) <= limit:
        return s, False
    return s[:limit], True


def _case_content(case: dict[str, Any]) -> str:
    """读取调研时已落盘的案例全文；无本地全文时返回空（零网络请求）。"""
    stored, _ = _cap_text(case.get("content"))
    if stored:
        return stored
    path_text = str(case.get("local_path") or "").strip()
    if not path_text:
        return ""
    path = Path(path_text)
    if not path.exists():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if path.suffix.lower() == ".json":
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            data = None
        if isinstance(data, dict):
            parts = [
                str(data.get(key)).strip()
                for key in (
                    "title", "company", "location", "summary",
                    "description", "requirements", "content",
                )
                if str(data.get(key) or "").strip()
            ]
            if parts:
                text = "\n".join(parts)
    capped, _ = _cap_text(text)
    return capped


def _delegate_plan(kind: str, available: list[str]) -> dict[str, Any]:
    """子 Agent 委派方案。

    子 Agent 由宿主 harness 的 Task 工具发起（opencode task/subagent、Claude Code Task）；
    仓库已提供 research-analyst 定义（.opencode/agent 与 .claude/agents）。
    服务端只提供数据、分批清单与输出契约，不自行创建子 Agent。
    """
    scope = "岗位 JD" if kind == "jd" else "面经与他人发展路径"
    batches = [
        available[index:index + _DETAIL_MAX_IDS]
        for index in range(0, len(available), _DETAIL_MAX_IDS)
    ]
    prompt = (
        f"任务：审阅调研数据（{scope}）并返回结论。\n"
        f'1) 先调用 read_research_details(kind="{kind}") 获取花名册与聚合摘要；\n'
        f'2) 依据岗位方向、技能匹配、届别/学历/城市等条件，选择 3-5 条最相关的条目，'
        f'再调用 read_research_details(kind="{kind}", ids=[...]) 读取全文；'
        f"单次不超过 {_DETAIL_MAX_IDS} 条，必要时参考 id_batches 分批；\n"
        "3) 只返回 JSON："
        '{"conclusions": [{"point": "...", "evidence_ids": ["..."]}], '
        '"shortlist": [{"id": "...", "reason": "...", "evidence": "..."}], '
        '"gaps": ["..."]}。'
        "每条结论必须引用具体标识作为依据，不复述原文。"
    )
    return {
        "subagent": "research-analyst",
        "mechanism": (
            "子 Agent 由宿主 harness 发起（opencode 的 task/subagent、Claude Code 的 Task）；"
            "仓库已提供 research-analyst 定义。父 Agent 负责发起并汇总其返回的结论与重点名单，"
            "服务端不创建子 Agent。"
        ),
        "invoke_example": (
            'task(subagent_type="research-analyst", description="调研 JD/面经分析", '
            'prompt="<delegate.prompt> + 调研方向/城市/学历等上下文")'
        ),
        "prompt": prompt,
        "id_batches": batches,
        "output_schema": {
            "conclusions": [{"point": "结论", "evidence_ids": ["JD01"]}],
            "shortlist": [{"id": "JD01", "reason": "入选理由", "evidence": "依据"}],
            "gaps": ["未覆盖或缺失的信息"],
        },
    }


@mcp.tool()
def read_research_details(ids: str = "", kind: str = "jd", limit: int = 6) -> str:
    """按花名册标识读取调研详情：先筛选、后读取，避免一次性加载全量正文。

    何时调用：
    - 调研完成后需要深读少量岗位或案例：先不传 ids 调用，获取花名册与聚合摘要；
      从中选择 3-5 个标识，再带 ids 读取全文；
    - 交由子 Agent 执行（宿主 harness 支持时）：用 Task 发起 research-analyst
      （仓库已提供 .opencode/agent 与 .claude/agents 定义），把花名册、聚合摘要与
      返回的 `delegate` 方案交给它，由它自行筛选并读取选定条目，回传结论与重点名单，
      父 Agent 仅汇总结论。

    Args:
        ids: 可选，JSON 数组或逗号/空格分隔的标识（如 "JD01,JD03"）；
            不传时返回花名册（标识与摘要）及聚合摘要
        kind: "jd"（岗位，默认）/ "case"（面经与他人发展路径）
        limit: 单次读取上限（默认 6，最大 10）；建议分批读取

    Returns:
        kind=jd：岗位描述与任职要求全文（读取本地已抓取数据，无网络请求）；
        kind=case：要点、命中原因与本地全文；无本地副本时返回原始链接，
        并提示通过 fetch_jd_detail 读取原帖。
    """
    kind = (kind or "jd").strip().lower()
    if kind not in {"jd", "case"}:
        return error_response(
            "INVALID_PARAM",
            "kind 只能是 jd（岗位）或 case（面经/发展路线）。",
            {"kind": kind, "allowed": ["jd", "case"]},
        )

    profile = load_profile()
    research = profile.research or {}
    pool = [
        item for item in (research.get("jd_samples" if kind == "jd" else "cases") or [])
        if isinstance(item, dict)
    ]
    if not pool:
        return error_response(
            "MISSING_DATA",
            "档案里还没有调研数据——先 research_market → gather_research_data。",
            {
                "hint": "调研报告会同时写入 profile.research，可再按 id 深读",
                "jd_count": len(research.get("jd_samples") or []),
                "case_count": len(research.get("cases") or []),
            },
        )

    digest = research.get("digest") or {}
    available = [str(item.get("id") or "") for item in pool if item.get("id")]
    wanted = _parse_id_list(ids)

    if not wanted:
        items = []
        for item in pool[:20]:
            if kind == "jd":
                items.append({
                    "id": item.get("id"),
                    "company": item.get("company"),
                    "title": item.get("title"),
                    "location": item.get("location"),
                    "salary": item.get("salary"),
                    "source": item.get("source"),
                    "brief": _brief(
                        item.get("description") or item.get("requirements")
                        or item.get("snippet") or ""
                    ),
                })
            else:
                items.append({
                    "id": item.get("id"),
                    "kind": item.get("kind"),
                    "title": item.get("title"),
                    "education_tag": item.get("education_tag"),
                    "year": item.get("year"),
                    "source": item.get("source"),
                    "brief": _brief((item.get("highlights") or [""])[0]),
                })
        return _json({
            "kind": kind,
            "count": len(pool),
            "items": items,
            "digest": digest,
            "delegate": _delegate_plan(kind, available),
            "instructions": [
                "先根据摘要选择 3-5 个标识，再带 ids 调用本工具读取全文；避免一次性读取全量。",
                "宿主 harness 支持子 Agent 时，由父 Agent 用 Task 发起 research-analyst"
                "（仓库已提供 .opencode/agent 与 .claude/agents 定义）：把花名册、聚合摘要与"
                " delegate.prompt 交给它，由它自行筛选并读取全文，回传结论与重点名单。",
            ],
            "next_steps": [
                f'read_research_details(ids="{available[0] if available else "JD01"}", kind="{kind}")',
            ],
        })

    unknown = [item_id for item_id in wanted if item_id not in available]
    if unknown:
        return error_response(
            "INVALID_PARAM",
            f"未知 id：{', '.join(unknown)}——可用 id：{', '.join(available[:20])}",
            {"available_ids": available[:20], "kind": kind},
        )

    limit = max(1, min(int(limit or 6), _DETAIL_MAX_IDS))
    selected = wanted[:limit]
    by_id = {str(item.get("id")): item for item in pool}
    items = []
    for item_id in selected:
        item = by_id[item_id]
        if kind == "jd":
            description, desc_cut = _cap_text(item.get("description"))
            requirements, req_cut = _cap_text(item.get("requirements"))
            items.append({
                "id": item_id,
                "company": item.get("company"),
                "title": item.get("title"),
                "location": item.get("location"),
                "salary": item.get("salary"),
                "source": item.get("source"),
                "url": item.get("url"),
                "fetched_at": item.get("fetched_at"),
                "description": description,
                "requirements": requirements,
                "text_truncated": desc_cut or req_cut,
            })
        else:
            content = _case_content(item)
            items.append({
                "id": item_id,
                "kind": item.get("kind"),
                "title": item.get("title"),
                "company": item.get("company"),
                "position": item.get("position"),
                "education_tag": item.get("education_tag"),
                "year": item.get("year"),
                "date": item.get("date"),
                "source": item.get("source"),
                "url": item.get("url"),
                "highlights": item.get("highlights") or [],
                "hit_terms": item.get("hit_terms") or [],
                "content": content,
                "content_status": "ok"
                if content
                else (item.get("content_status") or "unavailable"),
                "content_note": (
                    ""
                    if content
                    else (
                        "调研时未获取到全文，已标注缺口；"
                        "可人工打开来源链接核验，本读取不发起网络请求"
                    )
                ),
            })

    return _json({
        "kind": kind,
        "count": len(items),
        "items": items,
        "truncated": len(wanted) > len(selected),
        "note": f"单次读取上限为 {_DETAIL_MAX_IDS} 条；超出部分请分批读取。",
    })


def _render_report_message(report: dict[str, Any], paths: dict[str, str]) -> str:
    ctx = report.get("context") or {}
    counts = report.get("counts") or {}
    jd_n = counts.get("jd_samples") or 0
    case_n = counts.get("cases") or 0
    dropped_n = counts.get("dropped_no_detail") or 0
    list_only_n = counts.get("list_only") or 0
    fail_n = counts.get("source_fail") or 0
    empty_n = counts.get("source_empty") or 0
    gaps = report.get("gaps") or []

    statuses = report.get("source_status") or []
    # 源维度：同一来源只保留一个最终状态（ok > empty > failed），不按 scope 重复计数。
    states = report.get("source_states") or _source_final_states(statuses)
    # JD 源与案例源分开统计（口径写清），但同一 scope 内按来源去重。
    jd_ok_n = len({
        str(s.get("slug") or s.get("source") or "")
        for s in statuses
        if s.get("status") == "ok" and s.get("scope", "jd") == "jd"
    } - {""})
    case_ok_n = len({
        str(s.get("slug") or s.get("source") or "")
        for s in statuses
        if s.get("status") == "ok" and s.get("scope") == "cases"
    } - {""})
    scope_bits = []
    if jd_ok_n:
        scope_bits.append(f"JD 源 {jd_ok_n} 个可用")
    if case_ok_n:
        scope_bits.append(f"案例源 {case_ok_n} 个可用")
    ok_text = "、".join(scope_bits) or "0 个来源可用"

    source_bits = [
        f"{s.get('source')}（{s.get('count', 0)} 条）"
        for s in states
        if s.get("status") == "ok"
    ]
    fail_bits = [
        f"{s.get('source')}: {s.get('error') or '未获取到结果'}"
        for s in states
        if s.get("status") == "failed"
    ]

    filtered_n = counts.get("filtered_irrelevant") or 0
    lines = [
        f"市场调研完成（{report.get('direction') or ctx.get('goal') or '市场调研'}）"
        + (f" · 城市 {ctx.get('city')}" if ctx.get("city") else "")
        + (f" · 学历档 {ctx.get('education')}" if ctx.get("education") else ""),
        "",
        f"拿到：{jd_n} 条真实岗位样本、{case_n} 条同学历经历"
        + (f"（另有 {dropped_n} 条岗位因未获取到详情被剔除）" if dropped_n else "")
        + (f"（其中 {list_only_n} 条 BOSS 仅列表数据，未抓 JD 详情）" if list_only_n else "")
        + "；"
        f"{ok_text}，"
        + (f"{fail_n} 个源失败（原因已在报告的来源状态面板如实标注）" if fail_n else "无失败源")
        + (f"，{empty_n} 个源无结果" if empty_n else ""),
    ]
    if source_bits:
        lines.append(f"可用来源：{'、'.join(source_bits)}")
    if fail_bits:
        lines.append(f"失败来源：{'；'.join(fail_bits)}")
    item_bits = []
    if filtered_n:
        item_bits.append(f"方向不匹配过滤 {filtered_n} 条")
    if dropped_n:
        item_bits.append(f"无详情剔除 {dropped_n} 条")
    if item_bits:
        lines.append(
            "条目维度（不计入源状态，可在报告 JSON 复核）：" + "、".join(item_bits)
        )

    # 花名册 + 聚合摘要：消息内只保留标识与摘要，岗位全文留在报告/档案。
    # 全文读取由 read_research_details 按 id 完成，或交由子 Agent 深读并回传结论。
    roster_jd = report.get("jd_samples") or []
    if roster_jd:
        lines.append("")
        lines.append("【岗位花名册（标识与摘要，全文按需读取）】")
        for item in roster_jd[:_ROSTER_MAX]:
            brief = _brief(
                item.get("description") or item.get("requirements") or item.get("snippet") or ""
            )
            bits = [
                str(bits) for bits in (
                    item.get("company"), item.get("title"), item.get("location"),
                    item.get("salary") or "薪资未获取",
                    f"来源:{item.get('source') or '未知'}",
                ) if str(bits or "").strip()
            ]
            lines.append(f"#{item.get('id')} " + " | ".join(bits) + (f" | 摘要：{brief}" if brief else ""))
        if len(roster_jd) > _ROSTER_MAX:
            lines.append(f"……其余 {len(roster_jd) - _ROSTER_MAX} 条见报告。")
        lines.append(
            f"花名册共 {len(roster_jd)} 条；完整 JD 已写入报告与档案，未在本消息中展开。"
        )

    roster_cases = report.get("cases") or []
    if roster_cases:
        lines.append("")
        lines.append("【案例花名册（面经与他人路径，全文按需读取）】")
        for case in roster_cases[:_ROSTER_CASE_MAX]:
            brief = str((case.get("highlights") or [""])[0] or "")
            meta_bits = [
                str(bits) for bits in (
                    case.get("education_tag"), case.get("year"),
                    f"来源:{case.get('source') or '未知'}",
                ) if str(bits or "").strip()
            ]
            hits = "、".join(case.get("hit_terms") or [])
            lines.append(
                f"#{case.get('id')} [{case.get('kind') or '案例'}] {case.get('title','')}"
                + (f"（{' · '.join(meta_bits)}）" if meta_bits else "")
                + (f" | 命中:{hits}" if hits else "")
                + (f" | 摘要：{_brief(brief)}" if brief else "")
            )
        if len(roster_cases) > _ROSTER_CASE_MAX:
            lines.append(f"……其余 {len(roster_cases) - _ROSTER_CASE_MAX} 条见报告。")

    digest_lines = render_digest_lines(report.get("digest") or {})
    if digest_lines:
        lines.extend(["", *digest_lines])

    lines.extend(
        [
            "",
            "报告已入库（内容全部来自抓取数据，每条附来源链接，可逐条核验）：",
            f"- 可读全文 md：{paths['md']}",
            "- 查看入口：双击桌面上的「Career Kit」快捷方式，在控制台的「调研报告」卡片中打开",
        ]
    )
    if gaps:
        lines.append("")
        lines.append(f"数据缺口 {len(gaps)} 项（事实陈述，未编造替代）：")
        for g in gaps[:4]:
            lines.append(f"- {g.get('missing')}")
        if len(gaps) > 4:
            lines.append("……其余见报告「数据缺口」一节")
    lines.extend(
        [
            "",
            "下一步（按需读取，单次 3-5 条为宜）：",
            '- 直接读取：read_research_details(ids="JD01,JD03", kind="jd")；'
            '面经与他人路径使用 kind="case"',
            "- 发起子 Agent（宿主 harness 能力）：用 Task 调起 research-analyst，"
            "把花名册、聚合摘要与 delegate.prompt 交给它；由它自行筛选并分批读取，"
            "回传「结论 + 重点名单（含 id 与依据）」，父 Agent 负责合并",
            "",
            "差距分析（第 3 步）将直接引用本次调研数据。"
            "4 步流程：现状盘点 → 读取调研 → 两维分析 → 结果预览；"
            "用户可先阅读报告，确认后开始分析。",
        ]
    )
    return "\n".join(lines)
