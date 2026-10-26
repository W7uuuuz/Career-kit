"""MCP Resources——按需向客户端暴露文档。"""

from pathlib import Path

from .mcp_app import mcp

DOCS_ROOT = Path(__file__).parent.parent / "docs"


# ============================================================
# MCP Resources - 文档资源
# ============================================================


@mcp.resource("career-kit://docs/llms")
def get_llms_doc() -> str:
    """LLM 使用指南：工作流、工具分类、常见场景"""
    return (DOCS_ROOT / "llms.txt").read_text(encoding="utf-8")


@mcp.resource("career-kit://docs/workflow")
def get_workflow_doc() -> str:
    """工作流详解：完整工作流、前置条件、输入输出"""
    return (DOCS_ROOT / "workflow.md").read_text(encoding="utf-8")


@mcp.resource("career-kit://docs/scrapers")
def get_scrapers_doc() -> str:
    """企业数据源总览：已收录企业、数据源说明"""
    return (DOCS_ROOT / "scrapers.md").read_text(encoding="utf-8")


@mcp.resource("career-kit://docs/scrapers/{scraper_id}")
def get_scraper_doc(scraper_id: str) -> str:
    """特定企业使用教程（与 get_scraper_guide 工具同源）"""
    path = Path(__file__).parent / "scrapers" / scraper_id / "guide.md"
    if not path.exists():
        return f"文档不存在：{scraper_id}"
    return path.read_text(encoding="utf-8")


@mcp.resource("career-kit://docs/tools")
def get_tools_doc() -> str:
    """工具总览：MCP 工具列表、分类说明"""
    return (DOCS_ROOT / "tools.md").read_text(encoding="utf-8")


@mcp.resource("career-kit://docs/knowledge")
def get_knowledge_doc() -> str:
    """知识库结构：目录结构、文件格式"""
    return (DOCS_ROOT / "knowledge.md").read_text(encoding="utf-8")


@mcp.resource("career-kit://docs/examples")
def get_examples_doc() -> str:
    """示例目录：完整工作流示例、场景示例"""
    return (DOCS_ROOT / "examples" / "README.md").read_text(encoding="utf-8")
