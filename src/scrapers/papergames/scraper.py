"""叠纸游戏社会招聘 Scraper。"""

from __future__ import annotations

from .._platforms.feishu import FeishuScraper


class Scraper(FeishuScraper):
    """叠纸游戏（Papergames）社会招聘。"""

    COMPANY_SLUG = "papergames"
    COMPANY_NAME = "叠纸游戏"
    PORTAL_URL = "https://career.papegames.com/social/position/list"
    PORTAL_HOST = "career.papegames.com"
    DETAIL_URL_TEMPLATE = "https://career.papegames.com/social/position/{job_id}/detail"
