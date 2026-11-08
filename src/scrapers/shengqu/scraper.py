"""盛趣游戏社会招聘 Scraper。"""

from __future__ import annotations

from .._platforms.moka import MokaScraper


class Scraper(MokaScraper):
    """盛趣游戏社会招聘。"""

    COMPANY_SLUG = "shengqu"
    COMPANY_NAME = "盛趣游戏"
    PAGE_URL = "https://app.mokahr.com/apply/shengqu/4077"
    ORG_ID = "shengqu"
    SITE_ID = 4077
    MODULE_ID = ""
