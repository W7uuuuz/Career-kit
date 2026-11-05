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
import src.scrapers.jd.scraper as jd
import src.scrapers.kuaishou.scraper as kuaishou
import src.scrapers.meituan.scraper as meituan
import src.scrapers.netease.scraper as netease
import src.scrapers.pdd.scraper as pdd
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
# 美团
# ---------------------------------------------------------------------------


def test_meituan_search_and_detail(monkeypatch):
    payload = {
        "data": {
            "page": {"totalCount": 1},
            "list": [
                {
                    "name": "AI 工程师",
                    "jobUnionId": "m1",
                    "cityList": [{"name": "北京"}],
                    "department": [{"name": "AI 平台"}],
                    "jobFamily": "技术",
                    "workYear": "3-5年",
                    "jobDuty": "负责 AI 平台研发",
                    "jobRequirement": "熟悉 Python",
                }
            ],
        }
    }
    monkeypatch.setattr(meituan, "request_json", lambda *a, **k: payload)
    scraper = meituan.Scraper()

    rows = scraper.search(keyword="AI", city="北京", limit=1)
    assert rows[0]["title"] == "AI 工程师"
    assert rows[0]["location"] == "北京"
    assert rows[0]["url"].endswith("jobUnionId=m1")

    detail = scraper.get_detail(rows[0]["url"])
    assert detail["description"].startswith("部门: AI 平台")
    assert detail["company"] == "美团"


# ---------------------------------------------------------------------------
# 网易
# ---------------------------------------------------------------------------


def test_netease_search_and_detail(monkeypatch):
    payload = {
        "code": 200,
        "data": {
            "pages": 1,
            "total": 1,
            "list": [
                {
                    "id": 77492,
                    "name": "资深 Java 开发工程师",
                    "description": "负责 HR 系统",
                    "requirement": "熟悉 Java",
                    "firstDepName": "人力资源部",
                    "workPlaceNameList": ["杭州市"],
                    "reqEducationName": "本科",
                    "reqWorkYearsName": "3-5年",
                    "postTypeFullName": "技术",
                }
            ],
        },
    }
    monkeypatch.setattr(netease, "request_json", lambda *a, **k: payload)
    scraper = netease.Scraper()

    rows = scraper.search(keyword="Java", city="杭州", limit=1)
    assert rows[0]["title"] == "资深 Java 开发工程师"
    assert rows[0]["location"] == "杭州市"
    assert "id=77492" in rows[0]["url"]

    detail = scraper.get_detail(rows[0]["url"])
    assert detail["description"] == "负责 HR 系统"
    assert detail["company"] == "网易"


# ---------------------------------------------------------------------------
# 京东
# ---------------------------------------------------------------------------


def test_jd_search_and_detail(monkeypatch):
    payload = [
        {
            "positionNameOpen": "JAVA开发工程师",
            "requirementId": 226892,
            "workCity": "北京市",
            "positionDeptName": "技术研发",
            "workContent": "负责交易系统",
            "qualification": "熟悉 Java",
            "jobType": "研发类",
            "formatPublishTime": "2026-10-21",
        }
    ]
    monkeypatch.setattr(jd, "request_json", lambda *a, **k: payload)
    scraper = jd.Scraper()

    rows = scraper.search(keyword="Java", city="北京", limit=1)
    assert rows[0]["title"] == "JAVA开发工程师"
    assert rows[0]["location"] == "北京市"
    assert "requirementId=226892" in rows[0]["url"]

    detail = scraper.get_detail(rows[0]["url"])
    assert detail["description"] == "负责交易系统"
    assert detail["company"] == "京东"


# ---------------------------------------------------------------------------
# 快手
# ---------------------------------------------------------------------------


def test_kuaishou_parse_payload_and_detail():
    payload = {
        "result": {
            "total": 1,
            "list": [
                {
                    "id": 30644,
                    "name": "Java开发工程师（海外商业化）",
                    "workLocationCode": "Beijing",
                    "description": "负责海外商业化",
                    "positionDemand": "熟悉 Java",
                    "positionCategoryCode": "J0012",
                    "workExperienceCode": "4",
                }
            ],
        }
    }
    scraper = kuaishou.Scraper()

    rows = scraper._parse_payload(payload, keyword="Java", city="北京", limit=1)
    assert rows[0]["title"] == "Java开发工程师（海外商业化）"
    assert rows[0]["location"] == "北京"
    assert "positionId=30644" in rows[0]["url"]

    detail = scraper.get_detail(rows[0]["url"])
    assert detail["description"] == "负责海外商业化 熟悉 Java"
    assert detail["company"] == "快手"


# ---------------------------------------------------------------------------
# 拼多多
# ---------------------------------------------------------------------------


def test_pdd_parse_payload_and_detail_format():
    payload = {
        "result": {
            "list": [
                {
                    "name": "Java工程师",
                    "code": "T024973",
                    "workLocation": "上海",
                    "job": "研发类",
                    "updateTime": "2026-11-05",
                }
            ]
        }
    }
    scraper = pdd.Scraper()

    rows = scraper._parse_payload(payload, city="上海", limit=1)
    assert rows[0]["title"] == "Java工程师"
    assert rows[0]["location"] == "上海"
    assert "code=T024973" in rows[0]["url"]

    detail = scraper._format_detail(
        {
            "name": "Java工程师",
            "code": "T024973",
            "recruitType": "研发类",
            "workLocation": "上海",
            "jobDuty": "<p>负责交易系统<br/>保障稳定性</p>",
            "serveRequirement": "<p>熟悉 Java</p>",
            "bonus": "<p>有电商经验优先</p>",
        },
        rows[0]["url"],
    )
    assert detail["description"] == "负责交易系统\n保障稳定性"
    assert detail["requirements"] == "熟悉 Java"
    assert detail["benefits"] == "有电商经验优先"
    assert detail["company"] == "拼多多"


# ---------------------------------------------------------------------------
# 注册与路由
# ---------------------------------------------------------------------------


def test_new_scrapers_registered_with_params():
    by_id = {s["id"]: s for s in list_scrapers()}
    for cid in ("tencent", "baidu", "alibaba", "meituan", "netease", "jd", "kuaishou", "pdd"):
        assert cid in by_id
        assert by_id[cid]["params"]
        assert get_scraper(cid) is not None


def test_new_scraper_url_routing():
    cases = {
        "https://careers.tencent.com/jobdesc.html?postId=1": "tencent",
        "https://join.qq.com/post_detail.html?postid=1": "tencent",
        "https://talent.baidu.com/jobs/detail/SOCIAL/x": "baidu",
        "https://campus-talent.alibaba.com/campus/positionDetail?positionId=1": "alibaba",
        "https://zhaopin.meituan.com/web/position/detail?jobUnionId=1": "meituan",
        "https://hr.163.com/job-detail.html?id=1&lang=zh": "netease",
        "https://zhaopin.jd.com/web/job/job_info_list/3?requirementId=1": "jd",
        "https://zhaopin.kuaishou.cn/recruit/e/#/official/social/?positionId=1": "kuaishou",
        "https://careers.pddglobalhr.com/jobs/detail?code=T1": "pdd",
    }
    for url, expected in cases.items():
        scraper = get_scraper_for_url(url)
        assert scraper is not None and expected == scraper.COMPANY_SLUG
