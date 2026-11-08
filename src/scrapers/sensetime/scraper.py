"""商汤科技社会招聘 Scraper。"""

from __future__ import annotations

from .._platforms.feishu import FeishuScraper


class Scraper(FeishuScraper):
    """商汤科技（SenseTime）社会招聘。"""

    COMPANY_SLUG = "sensetime"
    COMPANY_NAME = "商汤科技"
    PORTAL_URL = "https://hr-jobs.sensetime.com/exp/position/list"
    PORTAL_HOST = "hr-jobs.sensetime.com"
    DETAIL_URL_TEMPLATE = "https://hr-jobs.sensetime.com/exp/position/{job_id}/detail"
