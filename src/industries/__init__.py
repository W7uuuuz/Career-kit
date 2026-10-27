"""行业配置包——数据采集通用，行业只提供解释层内容。"""

from .loader import get_industry, list_industries, resolve_industry

__all__ = ["get_industry", "list_industries", "resolve_industry"]
