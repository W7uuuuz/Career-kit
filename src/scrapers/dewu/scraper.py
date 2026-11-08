"""得物社会招聘 Scraper。"""

from __future__ import annotations

from .._platforms.feishu import FeishuScraper


class Scraper(FeishuScraper):
    """得物（Dewu）社会招聘。"""

    COMPANY_SLUG = "dewu"
    COMPANY_NAME = "得物"
    PORTAL_URL = "https://poizon.jobs.feishu.cn/index/position/list"
    PORTAL_HOST = "poizon.jobs.feishu.cn"
    DETAIL_URL_TEMPLATE = "https://poizon.jobs.feishu.cn/index/position/{job_id}/detail"
