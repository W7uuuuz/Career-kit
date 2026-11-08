"""脉脉社会招聘 Scraper。"""

from __future__ import annotations

from .._platforms.feishu import FeishuScraper


class Scraper(FeishuScraper):
    """脉脉（Maimai）社会招聘。"""

    COMPANY_SLUG = "maimai"
    COMPANY_NAME = "脉脉"
    PORTAL_URL = "https://maimai.jobs.feishu.cn/index"
    PORTAL_HOST = "maimai.jobs.feishu.cn"
