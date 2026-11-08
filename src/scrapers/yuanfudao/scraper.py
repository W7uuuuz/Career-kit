"""猿辅导校园招聘 Scraper。"""

from __future__ import annotations

from .._platforms.moka import MokaScraper


class Scraper(MokaScraper):
    """猿辅导校园招聘（粉笔站点）。"""

    COMPANY_SLUG = "yuanfudao"
    COMPANY_NAME = "猿辅导"
    PAGE_URL = "https://hr.yuanfudao.com/campus-recruitment/fenbi/47742"
    ORG_ID = "fenbi"
    SITE_ID = 47742
    MODULE_ID = ""
