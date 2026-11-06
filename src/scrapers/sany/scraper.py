"""三一集团社会招聘 Scraper。"""

from __future__ import annotations

from .._platforms.beisen import BeisenScraper


class Scraper(BeisenScraper):
    """三一集团社会招聘。"""

    COMPANY_SLUG = "sany"
    COMPANY_NAME = "三一集团"
    BASE_HOST = "https://sany.zhiye.com"
    PORTAL_PATH = "/social/jobs"
    CATEGORY = ["1"]
