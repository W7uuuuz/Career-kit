"""市场调研 MCP 工具——建档后的独立一步：批量抓取真实 JD 与同学学历经历。

research_market 返回方法论与 4 步执行模板；gather_research_data 一次完成
多源抓取（目标 1 家 + 对照 2-4 家 + 同学历案例），报告由代码渲染落盘到
用户资产目录（~/CareerKit），并写入 profile.research 供差距分析引用。

红线：报告内容不经 LLM 之手（来源真实的硬保证）；源失败如实上报，绝不编造。
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

from ..case_search import collect_cases, resolve_company
from ..mcp_app import mcp
from ..research_digest import render_digest_lines
from ..research_report import build_report, save_report
from ..scrapers.boss.auth import has_valid_cookies as boss_has_valid_cookies
from ..scrapers.loader import get_job_detail, search_company_jobs
from .errors import InvalidJsonError, error_response
from .methodology import build_methodology_context
from .profile import load_profile
from .tool_helpers import _json

_MAX_SPECS = 6
_CASE_DEFAULT_LIMIT = 12
_BOSS_ALIASES = {"boss", "boss直聘", "zhipin", "看准"}
_ROSTER_MAX = 15
_ROSTER_CASE_MAX = 8
_BRIEF_LIMIT = 60
_DETAIL_MAX_IDS = 10
_DETAIL_TEXT_LIMIT = 6000


@mcp.tool()
def research_market() -> str:
    """市场调研：建档后的独立一步——批量抓取真实 JD 与同学学历经历。

    何时调用：finalize_profile 之后、analyze_gaps 之前（推荐顺序，
    差距分析会直接引用调研数据；无调研时分析只是软提示）。

    产出：调研报告三件套（md 可读 / html 阅读版 / json 原始数据）落盘到
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
            "index": existing.get("index"),
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
                      "（需要扫码登录一次）」，用户点头才加入并带 boss_confirmed=true；"
                      "用户拒绝就换成其他源，不得静默跳过",
            "output": {"menu": "目标方向 + 抓取名单 + 预计耗时 + 产出位置"},
            "checkpoint": False,
            "checkpoint_note": "宣告即执行；用户喊停才停；BOSS 源例外——必须先问用户",
        },
        {
            "step": 2,
            "name": "批量抓取",
            "action": "调用 gather_research_data(jd_specs, case_query, boss_confirmed) 一次完成："
                      "jd_specs 目标公司 1 条 + 对照 2-4 条（优先同城、优先含薪来源），"
                      "case_query 带 role/education（五档四层写法如「双非本」）/company/city。"
                      "含 BOSS 源时必须先问过用户并传 boss_confirmed=true——否则工具会"
                      "返回 CONFIRMATION_REQUIRED 让你去问；未登录会返回 LOGIN_REQUIRED，"
                      "此时先问用户「是否现在扫码登录」，不要直接宣布调研失败。"
                      "抓取阶段会逐条补抓岗位详情；未取得正文的岗位将被剔除，"
                      "因此耗时略高于纯列表抓取。"
                      "调用前播报「正在抓取 N 家岗位与案例，并补抓详情，约半分钟至一分钟」",
            "output": {
                "report_paths": {"md": "", "html": "", "json": "", "index": ""},
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
                      "（完整路径，双击 index.html 查看全部资产）→ 每条附来源链接可逐条核验",
            "output": {"summary_lines": 0, "path_shown": True, "gaps_reported": 0},
            "checkpoint": False,
            "checkpoint_note": "报告不阻塞查看；缺口如实陈述",
        },
        {
            "step": 4,
            "name": "衔接分析",
            "action": "按需读取全文：从花名册中选择 3-5 条，调用 "
                      "read_research_details(ids=...)，岗位用 kind=\"jd\"，"
                      "面经与他人路径用 kind=\"case\"；也可将花名册与聚合摘要交由"
                      "子 Agent 深读，由子 Agent 返回分析结论与重点名单，父 Agent 仅汇总结论。"
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
        "BOSS 源纪律：名单含 BOSS 直聘时，抓取前必须询问用户「是否抓取 BOSS 直聘"
        "（需扫码登录一次）」——用户同意后传 boss_confirmed=true；不同意则更换来源，"
        "不得静默跳过。若工具返回 LOGIN_REQUIRED / CONFIRMATION_REQUIRED，"
        "将问题转问用户并等待答复，不得自行判定调研失败。\n"
        "详情纪律：工具为每条岗位补抓正文；未取得详情的岗位将被剔除并计入数据缺口。"
        "汇报时须说明「已剔除 N 条未取得详情的岗位」，不得以标题代替完整 JD。\n"
        "花名册机制：gather 返回的花名册仅含标识与摘要，岗位/案例全文已写入报告与档案。"
        "读取全文须按 id 定向调用 read_research_details，单次建议 3-5 条；"
        "样本量较大时宜交由子 Agent 分批深读，并将结论与重点名单返回父 Agent。\n"
        "播报纪律：调用 gather_research_data 前说明「抓取哪些来源 + 约半分钟至一分钟」，"
        "不得静默执行。\n"
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
        cleaned = name.strip().lower()
        if not cleaned:
            continue
        if cleaned in _BOSS_ALIASES or resolve_company(cleaned) == "boss":
            return True
    return False


def _enrich_with_detail(
    slug: str, rows: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[str]]:
    """逐条补抓岗位详情；拿不到正文的岗位剔除（无详情岗位无调研价值）。

    Returns:
        (保留的岗位行, 被剔除的岗位标题)
    """
    kept: list[dict[str, Any]] = []
    dropped: list[str] = []
    for row in rows:
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
        enriched["detail_status"] = "ok"
        kept.append(enriched)
    return kept, dropped


@mcp.tool()
async def gather_research_data(
    jd_specs: str = "",
    case_query: str = "",
    direction: str = "",
    city: str = "",
    boss_confirmed: bool = False,
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
            BOSS 需要扫码登录（cookies 长期复用）；未确认会返回 CONFIRMATION_REQUIRED
            让你先去问用户，未登录会返回 LOGIN_REQUIRED 让你问用户是否现在登录。

    Returns:
        汇报文本：样本统计 + 来源成功/失败 + 报告完整路径（index.html 资产总览入口） +
        数据缺口 + 下一步衔接分析。报告内容 100% 代码渲染自抓取数据（不经 LLM）。

    纪律：
    - 详情必抓：每条岗位抓取正文（description/requirements）；无详情岗位直接剔除，
      剔除数量进来源面板与数据缺口（没有详情的岗位对调研没有价值）
    - 任一源失败不中断；失败原因进报告「来源状态面板」如实展示
    - BOSS 抓取前必须先问用户（boss_confirmed=true 才算确认）；登录缺失时先问
      「是否现在登录」再决定，不得把登录失败直接当调研失败宣布
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

    # BOSS 登录是交互式关卡：抓取前必须先问用户是否抓取/是否现在登录——
    # 直接开抓会在未登录时静默变成「源失败」，用户根本没机会选择（实测反馈）
    uses_boss = _uses_boss(specs, query)
    if uses_boss and not boss_confirmed:
        return error_response(
            "CONFIRMATION_REQUIRED",
            "调研范围含 BOSS 直聘：该源需要扫码登录（cookies 长期复用），"
            "抓取前必须先问用户是否进行 BOSS 抓取。",
            {
                "question": "是否抓取 BOSS 直聘？需要你扫码登录一次（登录态长期有效）。",
                "options": [
                    "同意：带 boss_confirmed=true 重新调用 gather_research_data",
                    "不同意：从 jd_specs / case_query 移除 boss 后重跑，其他源照常抓取",
                ],
                "login_command": f'"{sys.executable}" -m src.scrapers.boss.login',
                "rule": "把 question 原样转问用户并等待答复；不得静默跳过 BOSS 或直接宣布失败",
            },
        )
    if uses_boss and not boss_has_valid_cookies():
        return error_response(
            "LOGIN_REQUIRED",
            "BOSS 直聘尚未登录：调研需要先扫码登录一次（cookies 长期复用）。",
            {
                "question": "BOSS 直聘还未登录，是否现在扫码登录后再抓取？",
                "login_command": f'"{sys.executable}" -m src.scrapers.boss.login',
                "after_login": "登录完成后带 boss_confirmed=true 重新调用 gather_research_data",
                "decline": "用户不想登录时，从 jd_specs / case_query 移除 boss 再重跑（其他源照常）",
                "rule": "先问用户是否现在登录；不要把登录缺失直接当调研失败宣布",
            },
        )

    profile = load_profile()

    def _run() -> dict[str, Any]:
        families: list[dict[str, Any]] = []
        for spec in specs:
            raw_spec = dict(spec)
            raw_name = str(raw_spec.pop("company", "") or "")
            label = str(raw_spec.pop("label", "") or raw_name)
            if not raw_name:
                families.append(
                    {"slug": "", "label": label or "无效配置", "rows": [],
                     "status": "failed", "error": "spec 缺少 company 字段", "elapsed": 0.0}
                )
                continue
            slug = resolve_company(raw_name)
            t0 = time.perf_counter()
            try:
                resp = search_company_jobs(slug, **raw_spec)
            except Exception as exc:  # noqa: BLE001
                resp = {"error": f"{type(exc).__name__}: {exc}", "results": []}
            elapsed = time.perf_counter() - t0
            rows = resp.get("results") or []
            if resp.get("error") and not rows:
                families.append(
                    {"slug": slug, "label": label or slug, "rows": [], "status": "failed",
                     "error": str(resp["error"]), "elapsed": elapsed,
                     "dropped_no_detail": 0, "dropped_titles": []}
                )
            else:
                # 详情必抓：没有正文的岗位对调研没有价值——补抓后仍无详情则剔除，
                # 剔除数量进报告的来源面板与数据缺口（如实告知，不拿标题凑数）
                dropped: list[str] = []
                if rows:
                    rows, dropped = _enrich_with_detail(slug, rows)
                status = "ok" if rows else "empty"
                families.append(
                    {"slug": slug, "label": label or slug, "rows": rows,
                     "status": status, "error": "", "elapsed": elapsed,
                     "dropped_no_detail": len(dropped),
                     "dropped_titles": dropped[:5]}
                )

        cases_result: dict[str, Any] = {"cases": [], "warnings": [], "sources": {}}
        if role:
            cases_result = collect_cases(
                role=role,
                company=str(query.get("company") or ""),
                city=str(query.get("city") or ""),
                education=str(query.get("education") or ""),
                kind=str(query.get("kind") or "both"),
                limit=int(query.get("limit") or _CASE_DEFAULT_LIMIT),
            )

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
        gathered_payload = {
            "direction": direction_value or "市场调研",
            "city": city_value,
            "education_tag": education_value,
            "jd_families": families,
            "cases_result": cases_result,
        }
        return gathered_payload

    gathered = await asyncio.to_thread(_run)
    report = build_report(profile, gathered)
    counts = report.get("counts") or {}
    if not (counts.get("jd_samples") or counts.get("cases")):
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
            },
        )

    paths = await asyncio.to_thread(save_report, profile, report)
    return _render_report_message(report, paths)


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
    """本地案例文件 → 可读全文（JSON 按字段拼接，md 原样）。"""
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


@mcp.tool()
def read_research_details(ids: str = "", kind: str = "jd", limit: int = 6) -> str:
    """按花名册标识读取调研详情：先筛选、后读取，避免一次性加载全量正文。

    何时调用：
    - 调研完成后需要深读少量岗位或案例：先不传 ids 调用，获取花名册与聚合摘要；
      从中选择 3-5 个标识，再带 ids 读取全文；
    - 交由子 Agent 执行：将花名册与聚合摘要提供给子 Agent，由子 Agent 使用本工具
      读取选定条目，返回分析结论与重点名单，父 Agent 仅汇总结论。

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
            {"kind": kind},
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
            "instructions": [
                "先根据摘要选择 3-5 个标识，再带 ids 调用本工具读取全文；避免一次性读取全量。",
                "可将花名册与聚合摘要交由子 Agent：由子 Agent 读取选定条目并返回"
                "「分析结论 + 重点名单」，父 Agent 汇总结论。",
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
                "content_note": (
                    "" if content else "本地无全文：用 fetch_jd_detail(url) 获取原帖全文"
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
    fail_n = counts.get("source_fail") or 0
    empty_n = counts.get("source_empty") or 0
    gaps = report.get("gaps") or []

    statuses = report.get("source_status") or []
    # 复测 BUG #5：JD 源与案例源分开统计（口径写清，不混为「2 个来源可用」）
    jd_ok_n = sum(1 for s in statuses if s.get("status") == "ok" and s.get("scope", "jd") == "jd")
    case_ok_n = sum(1 for s in statuses if s.get("status") == "ok" and s.get("scope") == "cases")
    scope_bits = []
    if jd_ok_n:
        scope_bits.append(f"JD 源 {jd_ok_n} 个可用")
    if case_ok_n:
        scope_bits.append(f"案例源 {case_ok_n} 个可用")
    ok_text = "、".join(scope_bits) or "0 个来源可用"

    source_bits = [
        f"{s.get('source')}（{s.get('count', 0)} 条）"
        for s in statuses
        if s.get("status") == "ok"
    ]
    fail_bits = [
        f"{s.get('source')}: {s.get('error') or '未获取到结果'}"
        for s in statuses
        if s.get("status") == "failed"
    ]

    lines = [
        f"市场调研完成（{report.get('direction') or ctx.get('goal') or '市场调研'}）"
        + (f" · 城市 {ctx.get('city')}" if ctx.get("city") else "")
        + (f" · 学历档 {ctx.get('education')}" if ctx.get("education") else ""),
        "",
        f"拿到：{jd_n} 条真实岗位样本、{case_n} 条同学历经历"
        + (f"（另有 {dropped_n} 条岗位因未获取到详情被剔除）" if dropped_n else "")
        + "；"
        f"{ok_text}，"
        + (f"{fail_n} 个源失败（原因已在报告的来源状态面板如实标注）" if fail_n else "无失败源")
        + (f"，{empty_n} 个源无结果" if empty_n else ""),
    ]
    if source_bits:
        lines.append(f"可用来源：{'、'.join(source_bits)}")
    if fail_bits:
        lines.append(f"失败来源：{'；'.join(fail_bits)}")

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
            f"- 阅读版（推荐浏览器打开）：{paths['html']}",
            f"- 可读全文 md：{paths['md']}",
            f"- 资产总览入口：双击 {paths['index']}"
            "（调研报告 / 路线图 / 仪表盘统一入口）",
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
            "- 交由子 Agent：提供花名册与聚合摘要，由子 Agent 读取选定条目并返回"
            "「分析结论 + 重点名单」，父 Agent 汇总结论",
            "",
            "差距分析（第 3 步）将直接引用本次调研数据。"
            "4 步流程：现状盘点 → 读取调研 → 两维分析 → 结果预览；"
            "用户可先阅读报告，确认后开始分析。",
        ]
    )
    return "\n".join(lines)
