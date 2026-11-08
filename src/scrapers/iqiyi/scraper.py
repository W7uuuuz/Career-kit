"""爱奇艺社会招聘 Scraper。"""

from __future__ import annotations

from .._platforms.beisen import BeisenScraper


class Scraper(BeisenScraper):
    """爱奇艺社会招聘。"""

    COMPANY_SLUG = "iqiyi"
    COMPANY_NAME = "爱奇艺"
    BASE_HOST = "https://iqiyi.zhiye.com"
    PORTAL_PATH = "/social/jobs"
    CATEGORY = [1]
