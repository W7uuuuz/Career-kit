"""京东方（BOE）社会招聘 Scraper。"""

from __future__ import annotations

from .._platforms.beisen import BeisenScraper


class Scraper(BeisenScraper):
    """京东方社会招聘。"""

    COMPANY_SLUG = "boe"
    COMPANY_NAME = "京东方"
    BASE_HOST = "https://boe.zhiye.com"
    PORTAL_PATH = "/social/jobs"
    CATEGORY = [1]
