"""知乎社会招聘 Scraper。"""

from __future__ import annotations

from .._platforms.moka import MokaScraper


class Scraper(MokaScraper):
    """知乎社会招聘。"""

    COMPANY_SLUG = "zhihu"
    COMPANY_NAME = "知乎"
    PAGE_URL = "https://app.mokahr.com/apply/zhihu/78336"
    ORG_ID = "zhihu"
    SITE_ID = 78336
    MODULE_ID = "6448975909"
