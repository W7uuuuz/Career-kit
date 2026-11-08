"""Keep 社会招聘 Scraper。"""

from __future__ import annotations

from .._platforms.beisen import BeisenScraper


class Scraper(BeisenScraper):
    """Keep 社会招聘。"""

    COMPANY_SLUG = "keep"
    COMPANY_NAME = "Keep"
    BASE_HOST = "https://hr.keep.com"
    PORTAL_PATH = "/social/jobs"
    CATEGORY = [1]
