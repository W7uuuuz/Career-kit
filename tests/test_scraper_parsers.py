"""新增企业 scraper 的离线解析与路由测试。

所有网络请求都通过 monkeypatch 替换，CI 不依赖真实站点。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import src.scrapers.alibaba.scraper as alibaba
import src.scrapers.baidu.scraper as baidu
import src.scrapers.tencent.scraper as tencent
from src.scrapers import list_scrapers
from src.scrapers.loader import get_scraper, get_scraper_for_url


@pytest.fixture(autouse=True)
def _isolate_cache(tmp_path, monkeypatch):
    """把缓存目录指到临时目录，避免测试互相污染。"""
    import src.scrapers.base as base

    monkeypatch.setattr(base, "CACHE_DIR", tmp_path)


# ---------------------------------------------------------------------------
# 腾讯
# ---------------------------------------------------------------------------


def test_tencent_social_search_and_detail(monkeypatch):
    def fake_request(client, method, url, **kwargs):
        if url.endswith("/post/Query"):
            return {
                "Code": 200,
                "Data": {
                    "Count": 1,
                    "Posts": [
                        {
                            "PostId": "p1",
                            "RecruitPostName": "AI 工程师",
                            "LocationName": "深圳",
                            "BGName": "CSIG",
                            "CategoryName": "技术",
                            "Responsibility": "负责 AI 平台研发",
                            "PostURL": "http://careers.tencent.com/jobdesc.html?postId=p1",
                        }
                    ],
                },
            }
        if url.endswith("/post/ByPostId"):
            return {
                "Code": 200,
                "Data": {
                    "RecruitPostName": "AI 工程师",
                    "LocationName": "深圳",
                    "BGName": "CSIG",
                    "Responsibility": "负责 AI 平台研发",
                    "Requirement": "熟悉 Python",
                    "PostURL": "https://careers.tencent.com/jobdesc.html?postId=p1",
                },
            }
        raise AssertionError(url)

    monkeypatch.setattr(tencent, "request_json", fake_request)
    scraper = tencent.Scraper()

    rows = scraper.search(keyword="AI", scope="social", limit=1)
    assert rows[0]["title"] == "AI 工程师"
    assert rows[0]["url"].startswith("https://")
    assert rows[0]["source"] == "tencent"

    detail = scraper.get_detail(rows[0]["url"])
    assert detail["requirements"] == "熟悉 Python"
    assert detail["company"] == "腾讯"


def test_tencent_campus_scope_mapping(monkeypatch):
    def fake_request(client, method, url, **kwargs):
        if url.endswith("/getProjectMapping"):
            return {
                "status": 0,
                "data": [
                    {"recruitType": 1, "subProjectList": [{"mappingId": 1, "projectName": "校招"}]},
                    {"recruitType": 2, "subProjectList": [{"mappingId": 2, "projectName": "实习"}]},
                ],
            }
        if url.endswith("/position/searchPosition"):
            assert kwargs["json_body"]["projectMappingIdList"] == [2]
            return {
                "status": 0,
                "data": {
                    "positionList": [
                        {
                            "postId": "c1",
                            "positionTitle": "AI 全栈",
                            "workCities": "深圳 北京",
                            "bgs": "CSIG",
                            "projectName": "应届实习",
                            "recruitLabelName": "实习生",
                        }
                    ]
                },
            }
        raise AssertionError(url)

    monkeypatch.setattr(tencent, "request_json", fake_request)
    scraper = tencent.Scraper()
    rows = scraper.search(keyword="AI", scope="intern", limit=1)
    assert rows[0]["title"] == "AI 全栈"
    assert rows[0]["url"].endswith("postid=c1")


# ---------------------------------------------------------------------------
# 百度
# ---------------------------------------------------------------------------


def test_baidu_search_and_detail_fallback(monkeypatch):
    list_payload = {
        "status": "ok",
        "data": {
            "total": "1",
            "hasNextPage": False,
            "list": [
                {
                    "postId": "b1",
                    "name": "AI 产品经理",
                    "workContent": "负责 AI 产品",
                    "serviceCondition": "本科及以上",
                    "workPlace": "北京市",
                    "bgShortName": "MEG",
                    "postType": "产品",
                }
            ],
        },
    }

    def fake_request(client, method, url, **kwargs):
        if url.endswith("/getPostListNew"):
            return list_payload
        if url.endswith("/getPostDetail"):
            return {"status": "fail", "message": "当前职位正在发布中"}
        raise AssertionError(url)

    monkeypatch.setattr(baidu, "request_json", fake_request)
    scraper = baidu.Scraper()

    rows = scraper.search(keyword="AI", scope="social", limit=1)
    assert rows[0]["title"] == "AI 产品经理"
    assert rows[0]["url"].endswith("/SOCIAL/b1")

    detail = scraper.get_detail(rows[0]["url"])
    assert "详情接口暂不可用" in detail["_note"]
    assert detail["description"] == "负责 AI 产品"


def test_baidu_city_filter(monkeypatch):
    payload = {
        "status": "ok",
        "data": {
            "hasNextPage": False,
            "list": [
                {"postId": "b1", "name": "北京岗", "workPlace": "北京市"},
                {"postId": "b2", "name": "上海岗", "workPlace": "上海市"},
            ],
        },
    }
    monkeypatch.setattr(baidu, "request_json", lambda *a, **k: payload)
    rows = baidu.Scraper().search(keyword="AI", city="上海", limit=5)
    assert [r["title"] for r in rows] == ["上海岗"]


# ---------------------------------------------------------------------------
# 阿里
# ---------------------------------------------------------------------------


def test_alibaba_search_and_detail(monkeypatch):
    batches = [
        {"batchId": 1, "batchName": "校招", "category": "graduate"},
        {"batchId": 2, "batchName": "实习", "category": "internship"},
    ]
    monkeypatch.setattr(alibaba, "_BATCH_CACHE", batches)
    monkeypatch.setattr(alibaba, "_acquire_token", lambda client: "token")

    def fake_request(client, method, url, **kwargs):
        if url.endswith("/position/search"):
            return {
                "data": {
                    "datas": [
                        {
                            "id": 101,
                            "name": "AI 工程师",
                            "workLocations": ["杭州"],
                            "categoryName": "技术类",
                            "categoryType": "freshman",
                            "circleNames": ["阿里云"],
                        }
                    ]
                }
            }
        if url.endswith("/position/detail"):
            return {
                "data": {
                    "name": "AI 工程师",
                    "description": "负责 AI 平台",
                    "requirement": "熟悉 Python",
                    "workLocations": ["杭州"],
                    "circleNames": ["阿里云"],
                    "batchName": "校招",
                    "categoryName": "技术类",
                }
            }
        raise AssertionError(url)

    monkeypatch.setattr(alibaba, "request_json", fake_request)
    scraper = alibaba.Scraper()

    rows = scraper.search(keyword="AI", scope="campus", limit=1)
    assert rows[0]["title"] == "AI 工程师"
    assert rows[0]["location"] == "杭州"

    detail = scraper.get_detail(rows[0]["url"])
    assert detail["description"] == "负责 AI 平台"
    assert detail["company"] == "阿里巴巴"


# ---------------------------------------------------------------------------
# 注册与路由
# ---------------------------------------------------------------------------


def test_new_scrapers_registered_with_params():
    by_id = {s["id"]: s for s in list_scrapers()}
    for cid in ("tencent", "baidu", "alibaba"):
        assert cid in by_id
        assert by_id[cid]["params"]
        assert get_scraper(cid) is not None


def test_new_scraper_url_routing():
    cases = {
        "https://careers.tencent.com/jobdesc.html?postId=1": "tencent",
        "https://join.qq.com/post_detail.html?postid=1": "tencent",
        "https://talent.baidu.com/jobs/detail/SOCIAL/x": "baidu",
        "https://campus-talent.alibaba.com/campus/positionDetail?positionId=1": "alibaba",
    }
    for url, expected in cases.items():
        scraper = get_scraper_for_url(url)
        assert scraper is not None and scraper.COMPANY_SLUG == expected
