"""游族网络社会招聘 Scraper。"""

from __future__ import annotations

from .._platforms.moka import MokaScraper


class Scraper(MokaScraper):
    """游族网络社会招聘。"""

    COMPANY_SLUG = "yoozoo"
    COMPANY_NAME = "游族网络"
    PAGE_URL = "https://app.mokahr.com/social-recruitment/yoozoo/91950"
    ORG_ID = "yoozoo"
    SITE_ID = 91950
    MODULE_ID = ""
