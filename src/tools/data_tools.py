"""本地检索、计划导入与企业数据抓取 MCP 工具。"""

from __future__ import annotations

import asyncio
import json
import sys

from ..mcp_app import mcp
from ..scrapers import get_job_detail, list_scrapers, search_company_jobs
from ..scrapers.loader import read_scraper_guide
from .errors import error_response
from .plan_importer import parse_plan_file
from .profile import load_profile
from .tool_helpers import server_fingerprint_line

# BOSS 登录是交互式关卡：命中登录缺失时要把问题交给用户，而不是直接判失败
_BOSS_IDS = {"boss", "boss直聘", "zhipin", "看准"}


@mcp.tool()
def search_knowledge(query: str) -> str:
    """检索本地知识库（用户积累的求职资料）。

    只搜索用户主目录 ~/.career-kit/knowledge/：scraper 抓取自动存入的 JD/面经，
    以及用户手动放入的简历、市场资料。不联网，不调用 LLM。

    何时调用：
    - 分析前查找已积累的同背景案例、目标公司 JD
    - 查询之前抓取过的面经内容

    Args:
        query: 搜索关键词
            示例：「AI Agent 面经」「字节跳动 JD」「双非 转 AI」

    Returns:
        每条含来源文件路径、相关度、内容预览。
        无结果时返回下一步指引（用 fetch_company_jobs 抓取）——
        此时不要基于自身知识编造市场数据。
    """
    from .knowledge_search import MIN_RELEVANCE, search_knowledge as do_search

    result = do_search(query)
    results = result["results"]

    if not results:
        weakest = result.get("weakest_dropped", 0)
        dropped_note = (
            f"另有 {weakest} 条弱相关材料未返回（低于相关度阈值 {MIN_RELEVANCE}）。\n\n" if weakest else ""
        )
        return (
            f"【知识库检索】{query}\n\n"
            "知识库中暂无相关资料。\n\n" + dropped_note +
            "下一步建议：\n"
            "1. 调用 fetch_company_jobs 抓取实时岗位数据（自动存入知识库）\n"
            "2. 用 fetch_jd_detail 获取 JD 全文\n"
            "3. 不要基于 LLM 自身知识编造市场数据——分析必须基于真实数据"
        )

    lines = [f"【知识库检索】{query} — 找到 {result['count']} 条：\n"]
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. **来源**: {r['source']}（相关度 {r['relevance']}）")
        preview = r["content"][:300].replace("\n", " ")
        lines.append(f"   {preview}")
        lines.append("")

    lines.append("需要完整内容时，直接读取对应文件路径。")
    weakest = result.get("weakest_dropped", 0)
    if weakest:
        lines.append(f"另有 {weakest} 条弱相关材料未展示（低于相关度阈值，容易误导分析——需要时用更具体的关键词检索）。")
    lines.append("下一步：需要更多实时数据时调用 fetch_company_jobs；数据齐备后进入 analyze_gaps。")
    return "\n".join(lines)


@mcp.tool()
def import_plan(file_path: str) -> str:
    """导入已有的职业规划文档。

    支持 PDF、DOCX、Markdown、TXT 格式。
    如果已有计划，会在对话中对比新旧内容，由用户决定取舍。

    Args:
        file_path: 计划文件的绝对路径
    """
    # 解析计划文件
    try:
        new_plan_text = parse_plan_file(file_path)
    except FileNotFoundError as e:
        return error_response("MISSING_DATA", str(e), {"file_path": file_path})
    except ValueError as e:
        return error_response("INVALID_JSON", str(e), {"file_path": file_path})

    profile = load_profile()

    # 如果没有旧计划，提示 LLM 走标准路线图链路导入
    if not profile.plan:
        return (
            f"--- PLAN CONTENT ---\n{new_plan_text}\n--- END ---\n\n"
            "这是新导入的计划文档。请将其整理为路线图结构后调用 save_roadmap(roadmap_json) 保存：\n"
            "schema 参考 sop/roadmap.yaml 的 output_schema（任务字段为 name/description/priority）。\n"
            "下一步：与用户确认取舍后调用 save_roadmap。"
        )

    # 有旧计划时：对比与取舍在对话中完成，落盘走 save_roadmap
    return (
        f"--- NEW PLAN CONTENT ---\n{new_plan_text}\n--- END ---\n\n"
        "检测到已有计划档案。请在对话中向用户呈现新旧计划的差异，"
        "由用户决定保留哪些内容；确认后把最终版整理为路线图结构，调用 save_roadmap(roadmap_json) 保存。\n"
        "下一步：save_roadmap。"
    )


@mcp.tool()
def get_scraper_guide(company: str) -> str:
    """获取指定企业数据源的完整使用教程。

    何时调用：第一次使用某个数据源前（或在 fetch_company_jobs 报错后）调用，
    了解该源能搜什么、参数语义、返回字段、登录要求和失败处理。

    Args:
        company: 企业 ID（通过 list_data_sources 获取）
            示例：bytedance
    """
    guide = read_scraper_guide(company)
    if guide is None:
        available = ", ".join(s["id"] for s in list_scrapers()) or "无"
        return (
            f"「{company}」没有使用指南或不是已注册的数据源。\n"
            f"可用数据源：{available}\n"
            "下一步：调用 list_data_sources 查看可用来源。"
        )
    return guide + "\n\n下一步：按教程调用 fetch_company_jobs。"


@mcp.tool()
def list_data_sources() -> str:
    """列出所有已注册的企业招聘数据源。

    何时调用：第一次需要真实岗位/面经数据时先调用本工具，
    看有哪些源、各支持什么参数；然后用 get_scraper_guide(company)
    查看目标源的完整教程（返回字段、示例、注意事项），再调 fetch_company_jobs。
    """
    scrapers = list_scrapers()

    if not scrapers:
        return "暂无已注册的企业数据源。社区贡献请参考 src/scrapers/ 目录。"

    lines = ["【已注册企业招聘数据源】\n"]
    for s in scrapers:
        lines.append(f"## {s['name']}（ID: {s['id']}）")
        if s.get("description"):
            lines.append(f"  {s['description']}")

        params = s.get("params", {})
        if params:
            lines.append("  支持的搜索参数：")
            for pname, pinfo in params.items():
                req = "（必填）" if isinstance(pinfo, dict) and pinfo.get("required") else "（可选）"
                desc = pinfo.get("description", "") if isinstance(pinfo, dict) else str(pinfo)
                lines.append(f"    - {pname}{req}: {desc}")

        lines.append(f"  详细用法：get_scraper_guide(company=\"{s['id']}\")")
        lines.append("")

    lines.append("---")
    lines.append("使用原则：params 只传上表列出的参数，不要自造参数名；")
    lines.append("搜索失败时按错误信息处理，不要编造岗位数据。")
    lines.append("下一步：先用 get_scraper_guide 读教程，再调用 fetch_company_jobs。")
    return "\n".join(lines)


@mcp.tool()
async def fetch_company_jobs(company: str, params: str = "{}") -> str:
    """搜索指定企业的岗位或面经（实时抓取真实数据）。

    何时调用：需要真实岗位数据（差距分析、路线图、薪资行情）或面经数据时调用。
    前置条件：先调用 list_data_sources 查看该企业支持的参数，params 只传列出的参数。

    Args:
        company: 企业 ID（通过 list_data_sources 获取）
            示例：bytedance
        params: 搜索参数 JSON 字符串（各企业支持的参数不同）
            示例：'{"keyword":"AI Agent", "city":"北京"}'

    Returns:
        每行一个岗位：标题 | 地点 | 薪资（如有）、链接、内容摘要。
        boss 返回岗位（含薪资范围）；其余 JD 源不公开薪资（见各源 guide）；
        nowcoder 返回面经，github 返回经验帖。
        失败时返回错误原因和恢复建议——此时如实告知用户，不要编造数据。
        BOSS 直聘需要登录：未登录会返回 LOGIN_REQUIRED（附问题与登录命令）——
        先问用户「是否现在扫码登录」，不要把登录缺失直接当抓取失败宣布。
    """
    try:
        params_dict = json.loads(params) if params else {}
    except (json.JSONDecodeError, TypeError) as exc:
        return error_response(
            "INVALID_JSON",
            f"params JSON 解析失败：{exc}",
            {"raw": params[:200]},
        )

    # BOSS 登录前置关卡：未登录时先让用户决定「是否现在登录」，不要抓完再报失败
    if company.strip().lower() in _BOSS_IDS:
        from ..scrapers.boss.auth import has_valid_cookies

        if not has_valid_cookies():
            return error_response(
                "LOGIN_REQUIRED",
                "BOSS 直聘尚未登录（cookies 未就绪）——该源需要扫码登录一次，"
                "登录态长期复用。",
                {
                    "question": "BOSS 直聘还未登录，是否现在扫码登录后再抓取？",
                    "login_command": f'"{sys.executable}" -m src.scrapers.boss.login',
                    "after_login": "登录成功后重试 fetch_company_jobs(company=\"boss\", ...)",
                    "recovery": (
                        "用户不想登录时改用其他数据源（bytedance/nowcoder 等），"
                        "或用 import_jd / import_jd_file 导入用户手头的真实 JD"
                    ),
                    "rule": "把 question 转问用户并等待答复；不要把登录缺失直接当抓取失败宣布",
                },
            )

    # 抓取是阻塞 IO（含 Playwright 同步 API），移入工作线程执行，
    # 避免在事件循环线程内触发 "Sync API inside asyncio loop" 崩溃
    result = await asyncio.to_thread(search_company_jobs, company, **params_dict)

    if result.get("error"):
        recovery = (
            "可尝试：1) 换关键词重试 2) 换其他企业数据源 "
            "3) 用 import_jd / import_jd_file 导入用户手头的真实 JD "
            "4) 如确认数据不可用，如实告知用户，不要编造岗位数据\n"
            "若上面的自检路径不是当前开发的 Career Kit 仓库，说明 MCP 服务连了旧实例——"
            "重启 Agent 会话（opencode）即可切到新代码"
        )
        message = str(result["error"])
        if company.strip().lower() in _BOSS_IDS and "登录" in message:
            # BUG（实测）：BOSS 未登录时直接报失败，LLM 默认当「源不可用」跳过。
            # 正确流程是把「是否现在登录」交给用户决定，登录成功即可重试
            return error_response(
                "LOGIN_REQUIRED",
                f"{message}\n\n{server_fingerprint_line()}\n"
                "BOSS 直聘需要先登录——先问用户：是否现在扫码登录？"
                "同意（登录成功后重试 / 走 gather_research_data 时带 boss_confirmed=true）；"
                "不同意（改用其他数据源或导入手头 JD）。",
                {
                    "question": "BOSS 直聘还未登录，是否现在扫码登录后再抓取？",
                    "login_command": f'"{sys.executable}" -m src.scrapers.boss.login',
                    "recovery": recovery,
                    "rule": "把 question 转问用户并等待答复；不要把登录缺失直接当抓取失败宣布",
                },
            )
        # BUG-014：错误信息附带 [服务自检] 行——报错里的解释器路径属于旧实例时，
        # 用户能立刻看出「MCP 服务连的是旧进程/旧仓库」，而不是照提示把依赖装错地方
        return error_response(
            "ANALYSIS_FAILED",
            f"{message}\n\n{server_fingerprint_line()}",
            {
                "available": result.get("available", []),
                "recovery": recovery,
            },
        )

    count = result["count"]
    company_name = result["company"]

    if count == 0:
        return (
            f"「{company_name}」未找到匹配的岗位。\n\n"
            "建议：1) 换更宽泛的关键词重试 2) 尝试其他企业数据源（list_data_sources 查看）"
        )

    # 部分失败的警告信息
    warnings_list = result.get("warnings", [])

    lines = [f"【{company_name}】找到 {count} 个岗位：\n"]
    for i, job in enumerate(result["results"], 1):
        title = job.get("title", "未知岗位")
        location = job.get("location", "")
        salary = job.get("salary", "")
        url = job.get("url", "")

        loc_str = f" | {location}" if location else ""
        sal_str = f" | {salary}" if salary else ""
        lines.append(f"{i}. **{title}**{loc_str}{sal_str}")
        if url:
            lines.append(f"   链接：{url}")
        # 兼容 JD 类（summary）和面经类（snippet）字段名
        preview = job.get("summary") or job.get("snippet") or ""
        if preview:
            lines.append(f"   {preview[:100]}")
        elif job.get("snippet_status") == "unavailable":
            lines.append("   摘要未获取——点开链接或 fetch_jd_detail(url) 查看详情")
        lines.append("")

    if warnings_list:
        lines.append("---")
        lines.append("部分数据获取失败：")
        for w in warnings_list:
            lines.append(f"   - {w}")
        lines.append("")

    lines.append("获取岗位详情：fetch_jd_detail(url=\"具体岗位URL\")")
    has_salary = any(job.get("salary") for job in result["results"])
    if has_salary:
        lines.append("薪资行情可直接汇总以上各岗位的薪资范围，这是最真实的市场数据。")
    else:
        lines.append(
            "当前数据源未提供薪资；如需薪资行情，请补充 BOSS 直聘等含薪资来源。"
        )
    return "\n".join(lines)


@mcp.tool()
async def fetch_jd_detail(url: str, company: str = "") -> str:
    """获取岗位详情或面经全文（JD 完整描述、任职要求）。

    何时调用：fetch_company_jobs 结果中某个岗位/面经需要深入分析时调用。
    url 必须来自 fetch_company_jobs 的返回结果。

    Args:
        url: 岗位详情页 URL（来自 fetch_company_jobs 结果）
        company: 企业 ID（可选，不填则自动按 URL 匹配 Scraper）

    Returns:
        岗位：标题、公司、地点、薪资（如有）、岗位描述全文、任职要求。
        面经：标题、面试问题与经验全文。
    """
    # 同 fetch_company_jobs：阻塞抓取移入工作线程，规避事件循环内的同步 Playwright
    result = await asyncio.to_thread(get_job_detail, url, company if company else None)

    if result.get("error"):
        return error_response("ANALYSIS_FAILED", result["error"], {"url": url})

    lines = [f"## {result.get('title', '岗位详情')}"]
    if result.get("company"):
        lines.append(f"**公司**：{result['company']}")
    if result.get("location"):
        lines.append(f"**地点**：{result['location']}")
    if result.get("salary"):
        lines.append(f"**薪资**：{result['salary']}")
    lines.append("")

    if result.get("description"):
        lines.append("### 岗位描述")
        lines.append(result["description"])
        lines.append("")

    if result.get("requirements"):
        lines.append("### 任职要求")
        lines.append(result["requirements"])
        lines.append("")

    if result.get("benefits"):
        lines.append("### 福利待遇")
        lines.append(result["benefits"])
        lines.append("")

    # 面经类详情（nowcoder 等）正文在 content 字段——此前未渲染导致「标题+公司，无正文」
    if result.get("content"):
        lines.append("### 面经内容")
        lines.append(result["content"])
        lines.append("")

    lines.append("如需导入此 JD 进行差距分析，请调用 import_jd(jd_text=...)。")
    return "\n".join(lines)
