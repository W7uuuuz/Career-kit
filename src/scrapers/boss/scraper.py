"""BOSS 直聘 Scraper——CDP 接入（复用本地已登录 Chrome/Edge）。

核心思路：
1. 用户运行 ``python -m src.scrapers.boss.login`` 在专用浏览器扫码登录；
2. Scraper 通过 CDP 连接专用浏览器，旁听页面自身的搜索接口，拿明文薪资；
3. 详情按需交互式补抓，列表阶段只返回 list_only 行，不拖垮整批调研。

纪律：只返回真实抓到的岗位与薪资；失败如实上报，不编造。
"""

from __future__ import annotations

import sys
from typing import Any

from ..base import CompanyScraper
from . import cdp
from .auth import has_valid_cookies, invalidate_auth

BASE_URL = "https://www.zhipin.com"


def _login_required_message() -> str:
    return (
        "需要登录 BOSS 直聘（登录标记不存在、已超过 6 小时或专用浏览器不可用）。"
        "请在 career-kit 项目目录运行：\n"
        f'    "{sys.executable}" -m src.scrapers.boss.login\n'
        "使用当前 MCP 服务的解释器（绝对路径），避免裸 python 指向错误环境。\n"
        "扫码成功后登录标记按 6 小时有效期管理，过期需重新登录；"
        "若浏览器已关闭，抓取时会在后台自动拉起专用 profile。"
    )


def _env_anomaly_error(message: str) -> str:
    return (
        f"API 错误: {message}\n"
        "BOSS 登录态已被判定异常并销毁。环境异常通常是 BOSS 对当前网络/浏览器"
        "环境的判定：先关闭代理/VPN 或换网络，稍后再扫码；单纯重复扫码可能继续失败。\n"
        "重新登录：\n"
        f'    "{sys.executable}" -m src.scrapers.boss.login'
    )


def _resolve_city(city: str) -> str:
    """解析城市名/代码，返回 9 位城市码。"""
    _name, code = cdp.resolve_city(city)
    return code


def _map_job(raw: dict[str, Any]) -> dict[str, Any]:
    """兼容旧接口：把 API 原始条目映射为标题/公司/薪资等基础字段。"""
    job = cdp.map_api_job(raw) or {}
    return {
        "title": job.get("title", ""),
        "salary": job.get("salary", ""),
        "location": job.get("location", ""),
        "company": job.get("boss_name") or "公司名未获取",
        "experience": job.get("experience", ""),
        "degree": job.get("degree", ""),
        "url": job.get("job_link", ""),
        "job_id": job.get("encrypt_job_id", ""),
        "source": "boss",
    }


def _to_row(job: dict[str, Any]) -> dict[str, Any]:
    """列表 API → 统一行（研究阶段只保留列表数据）。"""
    summary = " | ".join(
        part
        for part in (
            job.get("skills"),
            job.get("job_labels"),
            job.get("welfare"),
        )
        if part
    )
    return {
        "title": job.get("title", ""),
        "company": job.get("boss_name") or "公司名未获取",
        "location": job.get("location", ""),
        "salary": job.get("salary", ""),
        "summary": summary,
        "url": cdp.build_detail_url(job) or job.get("job_link", ""),
        "source": "boss",
        "description": "",
        "requirements": "",
        "detail_status": "list_only",
        "skills": job.get("skills", ""),
        "job_labels": job.get("job_labels", ""),
        "welfare": job.get("welfare", ""),
        "boss_active_status": job.get("boss_active_status", ""),
        "experience": job.get("experience", ""),
        "degree": job.get("degree", ""),
    }


class Scraper(CompanyScraper):
    """BOSS 直聘 Scraper（CDP）。"""

    COMPANY_SLUG = "boss"
    search_cache_ttl = 3600
    detail_cache_ttl = 86400

    PARAMS: dict[str, dict[str, Any]] = {
        "keyword": {"required": True, "description": "搜索关键词（如 \"Python\"、\"前端\"、\"AI\"）"},
        "city": {"required": False, "description": "城市名（如 \"北京\"、\"上海\"、\"全国\"）或城市代码"},
        "experience": {"required": False, "description": "经验要求（如 \"1-3年\"、\"3-5年\"、\"不限\"）"},
        "degree": {"required": False, "description": "学历要求（如 \"本科\"、\"硕士\"、\"不限\"）"},
        "salary": {"required": False, "description": "薪资范围（如 \"15-25K\"、\"30-50K\"）"},
        "limit": {"required": False, "description": "返回数量上限，默认 20"},
    }

    def supports_url(self, url: str) -> bool:
        return "zhipin.com" in url

    def search(self, **kwargs: Any) -> list[dict[str, Any]]:
        """搜索岗位（CDP 列表，薪资为接口明文）。"""
        keyword = str(kwargs.get("keyword", "") or "").strip()
        city = str(kwargs.get("city", "全国") or "全国")
        limit = int(kwargs.get("limit", 20) or 20)

        if not keyword:
            return [{"error": "搜索关键词不能为空"}]

        if not has_valid_cookies():
            return [{"error": _login_required_message()}]

        try:
            _city_name, city_code = cdp.resolve_city(city)
        except cdp.CityResolutionError as exc:
            return [{"error": str(exc)}]

        search_cache = self._make_cache("search")
        key = self._cache_key(keyword=keyword, city=city_code, limit=limit)
        cached = search_cache.get(key)
        if cached is not None:
            return cached[:limit]

        try:
            jobs = cdp.scrape_list(keyword, city, limit=limit)
        except cdp.LoginGateError as exc:
            message = str(exc)
            if "登录态" in message or "限制状态" in message:
                invalidate_auth("cdp_login_gate")
            return [{"error": f"{message}\n\n{_login_required_message()}"}]
        except cdp.BossCDPError as exc:
            return [{"error": f"BOSS 抓取失败: {exc}"}]

        results = [_to_row(job) for job in jobs[:limit]]
        if results:
            search_cache.set(key, results)
        return results[:limit]

    def get_detail(self, url: str) -> dict[str, Any]:
        """获取岗位详情（CDP 打开详情页并提取 JD）。"""
        if "zhipin.com" not in url:
            return {"error": f"非 BOSS 直聘 URL: {url}"}

        if not has_valid_cookies():
            return {"error": _login_required_message()}

        detail_cache = self._make_cache("detail")
        key = self._cache_key(url=url)
        cached = detail_cache.get(key)
        if cached is not None:
            return cached

        try:
            detail = cdp.scrape_detail(url)
        except cdp.BossCDPError as exc:
            message = str(exc)
            if "登录墙" in message or "登录" in message:
                invalidate_auth("cdp_detail_login_required")
                return {"error": f"{message}\n\n{_login_required_message()}", "url": url}
            return {"error": message, "url": url}

        result = {
            "title": "",
            "company": "",
            "location": "",
            "salary": "",
            "description": detail.get("description", ""),
            "requirements": detail.get("requirements", ""),
            "benefits": "",
            "skills": detail.get("skills", ""),
            "boss_active_status": detail.get("boss_active_status", ""),
            "detail_status": "ok",
            "source": "boss",
            "url": url,
        }
        if result["description"]:
            detail_cache.set(key, result)
        return result

    # 兼容旧调用名（已切换为 CDP 实现）
    def _search_api(self, keyword: str, city: str, limit: int) -> list[dict[str, Any]]:
        return self.search(keyword=keyword, city=city, limit=limit)

    def _fetch_detail(self, url: str) -> dict[str, Any]:
        return self.get_detail(url)
