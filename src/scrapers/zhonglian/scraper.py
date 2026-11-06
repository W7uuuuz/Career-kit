"""中联重科社会招聘 Scraper。"""

from __future__ import annotations

from .._platforms.dayee import DayeeScraper


class Scraper(DayeeScraper):
    """中联重科社会招聘。"""

    COMPANY_SLUG = "zhonglian"
    COMPANY_NAME = "中联重科"
    BASE_HOST = "https://wecruit.hotjob.cn"
    SUITE_KEY = "SU60a6449a2f9d2430fdc11a19"
