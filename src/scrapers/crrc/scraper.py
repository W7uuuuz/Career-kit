"""中国中车社会招聘 Scraper。"""

from __future__ import annotations

from .._platforms.dayee import DayeeScraper


class Scraper(DayeeScraper):
    """中国中车社会招聘。"""

    COMPANY_SLUG = "crrc"
    COMPANY_NAME = "中国中车"
    BASE_HOST = "https://crrc.hotjob.cn"
    SUITE_KEY = "SU64d47c466202cc36e27a52d4"
