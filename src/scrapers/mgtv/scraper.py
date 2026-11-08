"""芒果TV社会招聘 Scraper。"""

from __future__ import annotations

from .._platforms.moka import MokaScraper


class Scraper(MokaScraper):
    """芒果TV社会招聘。"""

    COMPANY_SLUG = "mgtv"
    COMPANY_NAME = "芒果TV"
    PAGE_URL = "https://hr.mgtv.com/social-recruitment/mgtv/44505"
    ORG_ID = "mgtv"
    SITE_ID = 44505
    MODULE_ID = ""
