"""汇川技术社会招聘 Scraper。"""

from __future__ import annotations

from .._platforms.beisen import BeisenScraper


class Scraper(BeisenScraper):
    """汇川技术社会招聘。"""

    COMPANY_SLUG = "inovance"
    COMPANY_NAME = "汇川技术"
    BASE_HOST = "https://inovance.zhiye.com"
    PORTAL_PATH = "/social/jobs"
    CATEGORY = ["1"]
