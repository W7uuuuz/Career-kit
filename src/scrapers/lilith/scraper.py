"""莉莉丝游戏社会招聘 Scraper。"""

from __future__ import annotations

from .._platforms.feishu import FeishuScraper


class Scraper(FeishuScraper):
    """莉莉丝游戏（Lilith）社会招聘。"""

    COMPANY_SLUG = "lilith"
    COMPANY_NAME = "莉莉丝"
    PORTAL_URL = "https://lilithgames.jobs.feishu.cn/career/"
    PORTAL_HOST = "lilithgames.jobs.feishu.cn"
