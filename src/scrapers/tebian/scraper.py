"""特变电工社会招聘 Scraper。"""

from __future__ import annotations

from .._platforms.dayee import DayeeScraper


class Scraper(DayeeScraper):
    """特变电工社会招聘。"""

    COMPANY_SLUG = "tebian"
    COMPANY_NAME = "特变电工"
    BASE_HOST = "https://wecruit.hotjob.cn"
    SUITE_KEY = "SU612f55eebef57c0616450aa2"
