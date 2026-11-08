"""作业帮社会招聘 Scraper。"""

from __future__ import annotations

from .._platforms.moka import MokaScraper


class Scraper(MokaScraper):
    """作业帮社会招聘。"""

    COMPANY_SLUG = "zuoyebang"
    COMPANY_NAME = "作业帮"
    PAGE_URL = "https://job.zuoyebang.com/social-recruitment/zuoyebang/41328"
    ORG_ID = "zuoyebang"
    SITE_ID = 41328
    MODULE_ID = ""
