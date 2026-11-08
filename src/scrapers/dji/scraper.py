"""大疆社会招聘 Scraper。"""

from __future__ import annotations

from .._platforms.moka import MokaScraper


class Scraper(MokaScraper):
    """大疆社会招聘。"""

    COMPANY_SLUG = "dji"
    COMPANY_NAME = "大疆"
    PAGE_URL = "https://apply.careers.dji.com/social-recruitment/dji/170070"
    ORG_ID = "dji"
    SITE_ID = 170070
    MODULE_ID = ""
