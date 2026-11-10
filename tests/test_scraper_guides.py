"""scraper 使用指南完整性测试。

约定：每个注册在 config.yaml 的企业数据源，必须在其包目录内提供
guide.md 使用教程（LLM 通过 get_scraper_guide 按需读取）。
贡献新 scraper 时从 _template/guide.md 复制填写，本测试保证不漏。
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

SCRAPERS_DIR = Path(__file__).parent.parent / "src" / "scrapers"
REPO_ROOT = Path(__file__).parent.parent


def _registered_company_ids() -> list[str]:
    from src.scrapers.loader import list_scrapers

    return [s["id"] for s in list_scrapers()]


def _guide_text(company_id: str) -> str:
    return (SCRAPERS_DIR / company_id / "guide.md").read_text(encoding="utf-8")


def _guide_params(company_id: str) -> dict[str, bool]:
    """解析 guide 的「参数」表：返回 {参数名: 是否必填}。"""
    section = _guide_text(company_id).split("## 参数", 1)[1]
    section = section.split("\n## ", 1)[0]
    rows = [
        [cell.strip() for cell in line.strip().strip("|").split("|")]
        for line in section.splitlines()
        if line.strip().startswith("|")
    ]
    if not rows:
        raise AssertionError(f"{company_id}/guide.md 缺少参数表")
    header = rows[0]
    if "必填" not in header:
        raise AssertionError(f"{company_id}/guide.md 参数表缺少「必填」列")
    required_idx = header.index("必填")

    params: dict[str, bool] = {}
    for cells in rows[1:]:
        name = cells[0].strip("`").strip()
        if not name or set(name) <= set("-: "):
            continue
        value = cells[required_idx] if required_idx < len(cells) else ""
        if value not in {"是", "否"}:
            raise AssertionError(
                f"{company_id}/guide.md 参数 {name} 的必填值不合法：{value!r}（只能是 是/否）"
            )
        params[name] = value == "是"
    return params


def test_every_registered_scraper_has_guide():
    """每个已注册的企业源必须附带 guide.md。"""
    ids = _registered_company_ids()
    assert ids, "config.yaml 中没有注册任何 scraper"

    missing = [
        cid for cid in ids if not (SCRAPERS_DIR / cid / "guide.md").exists()
    ]
    assert not missing, f"以下企业源缺少 guide.md：{missing}（模板见 src/scrapers/_template/guide.md）"


def test_guides_have_required_sections():
    """guide.md 必须包含核心章节，保证 LLM 能按需取到关键信息。"""
    required = ["## 用途", "## 参数", "## 调用示例", "## 返回字段"]
    for cid in _registered_company_ids():
        content = (SCRAPERS_DIR / cid / "guide.md").read_text(encoding="utf-8")
        absent = [sec for sec in required if sec not in content]
        assert not absent, f"{cid}/guide.md 缺少章节：{absent}"


def test_get_scraper_guide_tool():
    """get_scraper_guide 对已知源返回教程内容，未知源返回可用列表。"""
    from src.server import get_scraper_guide

    for cid in _registered_company_ids():
        result = get_scraper_guide(company=cid)
        assert isinstance(result, str)
        assert len(result) > 100, f"{cid} 的指南内容过短"
        assert "没有使用指南" not in result

    result = get_scraper_guide(company="nonexistent")
    assert isinstance(result, str)
    assert "可用数据源" in result


def test_every_registered_scraper_declares_params():
    """每个已注册的企业源必须在类上声明 PARAMS（参数唯一事实源）。

    config.yaml 不再维护参数——list_data_sources 直接渲染类上的 PARAMS。
    """
    from src.scrapers.loader import get_scraper

    for cid in _registered_company_ids():
        scraper = get_scraper(cid)
        assert scraper is not None, f"{cid} 无法实例化"
        params = getattr(scraper, "PARAMS", None)
        assert isinstance(params, dict) and params, (
            f"{cid} 未声明 PARAMS 类属性（应包含 required/description），"
            f"参考 _template/scraper.py"
        )
        for pname, pinfo in params.items():
            assert isinstance(pinfo, dict) and "description" in pinfo, (
                f"{cid}.PARAMS['{pname}'] 缺少 description"
            )


def test_knowledge_writer_does_not_mutate_input():
    """知识库写入不得污染调用方的原始结果 dict（写入到临时目录验证）。"""
    import tempfile

    import src.scrapers.knowledge_writer as kw
    from src.tools.knowledge_search import search_knowledge  # noqa: F401  确保模块可导入

    with tempfile.TemporaryDirectory() as tmp:
        original_dir = kw.KNOWLEDGE_DIR
        kw.KNOWLEDGE_DIR = Path(tmp)
        try:
            original = {"title": "测试岗位", "url": "https://example.com/x"}
            payload = dict(original)
            result = kw.write_to_knowledge("testcompany.scraper", [payload], data_type="jds")

            assert result == 1
            # 原始 dict 不被污染
            assert "_fetched_at" not in payload
            assert "_source" not in payload
            assert payload == original
        finally:
            kw.KNOWLEDGE_DIR = original_dir


# ---------------------------------------------------------------------------
# 别名解析：companies.yaml + catalog.get_company 的唯一入口
# ---------------------------------------------------------------------------


def test_platform_ids_match_companies_yaml():
    """平台 id 唯一来源是 companies.yaml 的 platforms 段。"""
    from src.scrapers import catalog

    data = yaml.safe_load((SCRAPERS_DIR / "companies.yaml").read_text(encoding="utf-8"))
    expected = {
        str(item["id"]).lower()
        for item in data.get("platforms", [])
        if isinstance(item, dict) and item.get("id")
    }
    assert set(catalog.PLATFORM_IDS) == expected


def test_alias_resolution_uses_single_entry():
    from src.scrapers.loader import resolve_company

    assert resolve_company("美团") == "meituan"
    assert resolve_company("Meituan") == "meituan"
    assert resolve_company("meituan") == "meituan"
    assert resolve_company("看准") == "boss"
    assert resolve_company("字节") == "bytedance"
    assert resolve_company("阿里") == "alibaba"

    from src.case_search import resolve_company as case_resolve

    assert case_resolve("美团") == "meituan"


def test_get_scraper_guide_resolves_alias():
    from src.tools.data_tools import get_scraper_guide

    result = get_scraper_guide(company="美团")
    assert "没有使用指南" not in result
    assert "美团" in result


def test_resolve_company_scrapers_returns_all_sources():
    from src.scrapers.loader import resolve_company_scrapers

    alibaba_sources = resolve_company_scrapers("阿里")
    assert "alibaba" in alibaba_sources
    assert "alibaba_social" in alibaba_sources

    # 单源企业只返回自身；平台返回自身；未知返回空
    assert resolve_company_scrapers("美团") == ["meituan"]
    assert resolve_company_scrapers("boss") == ["boss"]
    assert resolve_company_scrapers("不存在") == []


def test_get_scraper_guide_mentions_related_alibaba_social():
    from src.tools.data_tools import get_scraper_guide

    result = get_scraper_guide(company="阿里")
    assert "alibaba_social" in result
    assert "暂未接入" not in result


def test_fetch_company_jobs_mentions_related_alibaba_social(monkeypatch):
    import asyncio

    import src.tools.data_tools as data_tools

    def fake_search(company, **kwargs):
        return {
            "company": "阿里巴巴（校招/实习）",
            "results": [{"title": "校招岗位", "url": "https://example.com/job/1"}],
            "count": 1,
        }

    monkeypatch.setattr(data_tools, "search_company_jobs", fake_search)
    out = asyncio.run(
        data_tools.fetch_company_jobs(company="阿里", params='{"keyword":"AI"}')
    )
    assert "alibaba_social" in out


def test_fetch_company_jobs_resolves_alias(monkeypatch):
    import asyncio

    import src.tools.data_tools as data_tools

    captured: dict[str, str] = {}

    def fake_search(company, **kwargs):
        captured["company"] = company
        return {"company": "美团", "results": [], "count": 0}

    monkeypatch.setattr(data_tools, "search_company_jobs", fake_search)
    out = asyncio.run(
        data_tools.fetch_company_jobs(company="Meituan", params='{"keyword":"AI"}')
    )
    assert captured["company"] == "meituan"
    assert "的 Scraper" not in out


# ---------------------------------------------------------------------------
# guide 语义：代表性源参数表 = PARAMS，关键参数确实改变请求
# ---------------------------------------------------------------------------


def test_representative_guide_params_match_params():
    from src.scrapers.loader import get_scraper

    for cid in ("boss", "bytedance", "nowcoder", "baidu", "tencent", "github"):
        scraper = get_scraper(cid)
        assert scraper is not None
        guide_params = _guide_params(cid)
        assert set(guide_params) == set(scraper.PARAMS), (
            f"{cid} guide 参数表与 PARAMS 不一致："
            f"guide={sorted(guide_params)} params={sorted(scraper.PARAMS)}"
        )
        for name, required in guide_params.items():
            expected = bool(scraper.PARAMS[name].get("required"))
            assert required is expected, (
                f"{cid}.{name} 必填不一致：guide={required} PARAMS={expected}"
            )


def test_nowcoder_order_changes_search_url():
    from src.scrapers.nowcoder.scraper import Scraper

    scraper = Scraper()
    url_create = scraper._build_search_url("Agent", "create", 1)
    url_quality = scraper._build_search_url("Agent", "quality", 2)

    assert "order=create" in url_create
    assert "order=hot" in url_quality
    assert "&page=2" in url_quality
    assert url_create != url_quality

    invalid = scraper.search(keyword="Agent", order="unknown")
    assert invalid and invalid[0].get("error")


# ---------------------------------------------------------------------------
# fetch_jd_detail 渲染 guide 承诺的字段
# ---------------------------------------------------------------------------


def test_fetch_jd_detail_renders_guide_fields(monkeypatch):
    import asyncio

    import src.tools.data_tools as data_tools

    fake = {
        "title": "AI Agent 工程师",
        "company": "测试公司",
        "location": "北京",
        "department": "AI 平台",
        "job_type": "技术",
        "project": "2027 届校招",
        "job_family": "研发族",
        "job_category": "算法",
        "education": "本科",
        "experience": "1-3年",
        "boss_active_status": "在线",
        "detail_status": "ok",
        "skills": ["Python", "RAG"],
        "description": "负责 Agent 开发",
        "requirements": "熟悉 LangGraph",
    }
    monkeypatch.setattr(data_tools, "get_job_detail", lambda url, company=None: fake)
    out = asyncio.run(data_tools.fetch_jd_detail(url="https://example.com/job/1"))

    for expected in (
        "AI 平台", "校招", "2027 届校招", "研发族", "算法", "本科", "1-3年",
        "在线", "ok", "Python、RAG",
    ):
        assert expected in out, f"详情渲染缺少字段值：{expected}"


# ---------------------------------------------------------------------------
# 单一事实源声明与 config 描述一致性
# ---------------------------------------------------------------------------


def test_docs_declare_single_source_of_truth():
    docs = (REPO_ROOT / "docs" / "scrapers.md").read_text(encoding="utf-8")
    readme = (SCRAPERS_DIR / "README.md").read_text(encoding="utf-8")

    for text in (docs, readme):
        for anchor in ("config.yaml", "companies.yaml", "PARAMS", "guide.md"):
            assert anchor in text, f"单一事实源声明缺少 {anchor}"
    assert "## 通用参数" not in docs
    assert "通用参数与贡献流程以" not in readme


def test_shein_oppo_config_descriptions_match_guides():
    config = yaml.safe_load((SCRAPERS_DIR / "config.yaml").read_text(encoding="utf-8"))
    shein = config["scrapers"]["shein"]["description"]
    oppo = config["scrapers"]["oppo"]["description"]

    for channel in ("社招", "校招", "实习", "不公开薪资"):
        assert channel in shein, f"SHEIN config 描述缺少 {channel}"
    assert "不公开薪资" in oppo
    assert "部分岗位公开薪资" not in oppo

    shein_guide = _guide_text("shein")
    for channel in ("social", "campus", "intern"):
        assert channel in shein_guide
    assert "不公开薪资" in _guide_text("oppo")

    docs = (REPO_ROOT / "docs" / "scrapers.md").read_text(encoding="utf-8")
    assert "| `shein` | SHEIN | JD（不公开薪资） | 社招 / 校招 / 实习 |" in docs
    assert "| `oppo` | OPPO | JD（不公开薪资） | 校招 / 国际化 / 博士项目 |" in docs
