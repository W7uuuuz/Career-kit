"""FastMCP 实例——工具模块共享的注册入口。"""

import warnings

# 抑制 pydantic_settings 对 mcp 内部 Settings 模型的误报告警（OBS-002）
try:
    from pydantic_settings.exceptions import IncompleteFieldDefinitionWarning

    warnings.filterwarnings("ignore", category=IncompleteFieldDefinitionWarning)
except ImportError:
    pass

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("career-kit")
