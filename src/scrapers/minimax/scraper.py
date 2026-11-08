"""MiniMax 社会招聘 Scraper。"""

from __future__ import annotations

from .._platforms.feishu import FeishuScraper


class Scraper(FeishuScraper):
    """MiniMax 社会招聘。"""

    COMPANY_SLUG = "minimax"
    COMPANY_NAME = "MiniMax"
    PORTAL_URL = "https://vrfi1sk8a0.jobs.feishu.cn/379481/"
    PORTAL_HOST = "vrfi1sk8a0.jobs.feishu.cn"
