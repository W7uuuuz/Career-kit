"""Soul 社会招聘 Scraper。"""

from __future__ import annotations

from .._platforms.feishu import FeishuScraper


class Scraper(FeishuScraper):
    """Soul 社会招聘。"""

    COMPANY_SLUG = "soul"
    COMPANY_NAME = "Soul"
    PORTAL_URL = "https://soulapp.jobs.feishu.cn/index"
    PORTAL_HOST = "soulapp.jobs.feishu.cn"
