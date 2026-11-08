"""哈啰社会招聘 Scraper。"""

from __future__ import annotations

from .._platforms.beisen import BeisenScraper


class Scraper(BeisenScraper):
    """哈啰社会招聘。"""

    COMPANY_SLUG = "hello"
    COMPANY_NAME = "哈啰"
    BASE_HOST = "https://hellobike.zhiye.com"
    PORTAL_PATH = "/social/jobs"
    CATEGORY = [1]
