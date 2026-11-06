"""阳光电源社会招聘 Scraper。"""

from __future__ import annotations

from .._platforms.moka import MokaScraper


class Scraper(MokaScraper):
    """阳光电源社会招聘。"""

    COMPANY_SLUG = "sungrow"
    COMPANY_NAME = "阳光电源"
    PAGE_URL = "https://app.mokahr.com/social-recruitment/sungrow/94415"
    ORG_ID = "sungrow"
    SITE_ID = 94415
    MODULE_ID = "5995705957"
