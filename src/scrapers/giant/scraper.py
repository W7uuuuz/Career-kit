"""巨人网络社会招聘 Scraper。"""

from __future__ import annotations

from .._platforms.moka import MokaScraper


class Scraper(MokaScraper):
    """巨人网络社会招聘。"""

    COMPANY_SLUG = "giant"
    COMPANY_NAME = "巨人网络"
    PAGE_URL = "https://app.mokahr.com/apply/ztgame/37485"
    ORG_ID = "ztgame"
    SITE_ID = 37485
    MODULE_ID = ""
