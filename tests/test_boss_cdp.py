"""BOSS CDP 纯函数与列表/详情映射测试（无网络、不开浏览器）。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import src.scrapers.boss.cdp as cdp
import src.scrapers.boss.scraper as scraper


class FakeCache:
    def __init__(self) -> None:
        self.values: dict = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value):
        self.values[key] = value


def _raw_job(**overrides):
    raw = {
        "jobName": "AI Agent 工程师",
        "salaryDesc": "25-45K·16薪",
        "cityName": "北京",
        "areaDistrict": "朝阳区",
        "businessDistrict": "望京",
        "brandName": "某科技公司",
        "skills": ["Python", "RAG"],
        "jobLabels": ["大模型", "Agent"],
        "welfareList": ["五险一金", "年终奖"],
        "encryptJobId": "JOB123",
        "encryptBrandId": "BRAND456",
        "bossOnline": True,
        "jobExperience": "3-5年",
        "jobDegree": "本科",
    }
    raw.update(overrides)
    return raw


def test_map_api_job_keeps_plaintext_salary():
    job = cdp.map_api_job(_raw_job())

    assert job is not None
    assert job["title"] == "AI Agent 工程师"
    assert job["salary"] == "25-45K·16薪"
    assert job["salary_source"] == "api"
    assert job["location"] == "北京·朝阳区·望京"
    assert job["boss_name"] == "某科技公司"
    assert job["skills"] == "Python | RAG"
    assert job["job_labels"] == "大模型 | Agent"
    assert job["welfare"] == "五险一金 | 年终奖"
    assert job["boss_active_status"] == "在线"
    assert job["job_link"] == "https://www.zhipin.com/job_detail/JOB123.html"


def test_map_api_jobs_reads_zpdata_joblist():
    data = {"zpData": {"jobList": [_raw_job(), "bad", _raw_job(encryptJobId="J2")]}}

    jobs = cdp.map_api_jobs(data)

    assert [job["encrypt_job_id"] for job in jobs] == ["JOB123", "J2"]


@pytest.mark.parametrize(
    ("payload", "status"),
    [
        ({"zpData": {"jobList": [_raw_job()]}}, cdp.LoginProbeStatus.AVAILABLE),
        (
            {"zpData": {"jobList": [_raw_job(salaryDesc="")]}},
            cdp.LoginProbeStatus.UNAUTHENTICATED,
        ),
        ({"code": 37, "message": "需要验证"}, cdp.LoginProbeStatus.RESTRICTED),
        ({"code": 1, "message": "访问频繁"}, cdp.LoginProbeStatus.RESTRICTED),
        ({"zpData": {"jobList": []}}, cdp.LoginProbeStatus.EMPTY),
        ({"code": 1, "message": "未知错误"}, cdp.LoginProbeStatus.RESPONSE_ERROR),
        ("not-json", cdp.LoginProbeStatus.RESPONSE_ERROR),
    ],
)
def test_classify_login_probe_response(payload, status):
    result = cdp.classify_login_probe_response(payload)
    assert result.status is status


def test_classify_http_restricted_and_unauthenticated():
    assert (
        cdp.classify_login_probe_response({}, http_status=401).status
        is cdp.LoginProbeStatus.UNAUTHENTICATED
    )
    assert (
        cdp.classify_login_probe_response({}, http_status=429).status
        is cdp.LoginProbeStatus.RESTRICTED
    )


def test_resolve_city_name_and_code():
    assert cdp.resolve_city("上海") == ("上海", "101020100")
    assert cdp.resolve_city("101020100") == ("上海", "101020100")
    assert cdp.resolve_city("999999999") == ("999999999", "999999999")


def test_resolve_city_rejects_unknown():
    with pytest.raises(cdp.CityResolutionError):
        cdp.resolve_city("不存在的城市")


def test_search_returns_list_only_rows(monkeypatch):
    monkeypatch.setattr(scraper, "has_valid_cookies", lambda: True)
    monkeypatch.setattr(scraper.Scraper, "_make_cache", lambda self, namespace: FakeCache())
    mapped = cdp.map_api_job(_raw_job())
    monkeypatch.setattr(scraper.cdp, "scrape_list", lambda *a, **k: [mapped])

    rows = scraper.Scraper().search(keyword="AI Agent", city="北京", limit=5)

    assert len(rows) == 1
    row = rows[0]
    assert row["detail_status"] == "list_only"
    assert row["description"] == ""
    assert row["requirements"] == ""
    assert row["salary"] == "25-45K·16薪"
    assert row["salary_source"] == "api"
    assert row["company"] == "某科技公司"
    assert row["source"] == "boss"
    assert row["url"].endswith("JOB123.html")
    assert row["skills"] == "Python | RAG"


def test_search_maps_cdp_failure_to_error(monkeypatch):
    monkeypatch.setattr(scraper, "has_valid_cookies", lambda: True)
    monkeypatch.setattr(scraper.Scraper, "_make_cache", lambda self, namespace: FakeCache())

    def _raise(*args, **kwargs):
        raise cdp.BossCDPError("未捕获到 BOSS 搜索响应")

    monkeypatch.setattr(scraper.cdp, "scrape_list", _raise)

    rows = scraper.Scraper().search(keyword="AI Agent", city="北京")

    assert "BOSS 抓取失败" in rows[0]["error"]


def test_get_detail_maps_cdp_detail(monkeypatch):
    monkeypatch.setattr(scraper, "has_valid_cookies", lambda: True)
    monkeypatch.setattr(scraper.Scraper, "_make_cache", lambda self, namespace: FakeCache())
    monkeypatch.setattr(
        scraper.cdp,
        "scrape_detail",
        lambda *a, **k: {
            "description": "负责 Agent 产品后端与 RAG 链路。",
            "requirements": "",
            "skills": "Python | LangGraph",
            "boss_active_status": "今日活跃",
        },
    )

    result = scraper.Scraper().get_detail("https://www.zhipin.com/job_detail/JOB123.html")

    assert result["detail_status"] == "ok"
    assert result["source"] == "boss"
    assert "Agent 产品" in result["description"]
    assert result["skills"] == "Python | LangGraph"
    assert result["boss_active_status"] == "今日活跃"


def test_get_detail_rejects_non_boss_url():
    result = scraper.Scraper().get_detail("https://example.com/job/1")
    assert "非 BOSS" in result["error"]
