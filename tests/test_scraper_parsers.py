"""新增企业 scraper 的离线解析与路由测试。

所有网络请求都通过 monkeypatch 替换，CI 不依赖真实站点。
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7

sys.path.insert(0, str(Path(__file__).parent.parent))

import src.scrapers._platforms.beisen as beisen_platform
import src.scrapers._platforms.dayee as dayee_platform
import src.scrapers._platforms.moka as moka_platform
import src.scrapers.alibaba.scraper as alibaba
import src.scrapers.alibaba_social.scraper as alibaba_social
import src.scrapers.ant.scraper as ant
import src.scrapers.baidu.scraper as baidu
import src.scrapers.bilibili.scraper as bilibili
import src.scrapers.boe.scraper as boe
import src.scrapers.crrc.scraper as crrc
import src.scrapers.ctrip.scraper as ctrip
import src.scrapers.didi.scraper as didi
import src.scrapers.huawei.scraper as huawei
import src.scrapers.jd.scraper as jd
import src.scrapers.kuaishou.scraper as kuaishou
import src.scrapers.meituan.scraper as meituan
import src.scrapers.netease.scraper as netease
import src.scrapers.pdd.scraper as pdd
import src.scrapers.sungrow.scraper as sungrow
import src.scrapers.tebian.scraper as tebian
import src.scrapers.tencent.scraper as tencent
import src.scrapers.xiaohongshu.scraper as xiaohongshu
import src.scrapers.xiaomi.scraper as xiaomi
import src.scrapers.zhonglian.scraper as zhonglian
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


def test_tencent_social_limit_paginates(monkeypatch):
    calls: list[tuple[int, int]] = []

    def fake_request(client, method, url, **kwargs):
        assert url.endswith("/post/Query")
        params = kwargs["params"]
        page = int(params["pageIndex"])
        size = int(params["pageSize"])
        calls.append((page, size))
        posts = [
            {
                "PostId": f"p{page}-{index}",
                "RecruitPostName": f"AI 工程师 {page}-{index}",
                "LocationName": "深圳",
                "BGName": "CSIG",
                "Responsibility": "负责 AI 平台研发",
                "PostURL": f"http://careers.tencent.com/jobdesc.html?postId=p{page}-{index}",
            }
            for index in range(size)
        ]
        return {"Code": 200, "Data": {"Posts": posts}}

    monkeypatch.setattr(tencent, "request_json", fake_request)
    rows = tencent.Scraper().search(keyword="AI", scope="social", limit=25)

    assert calls == [(1, 20), (2, 5)]
    assert len(rows) == 25


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


def test_baidu_limit_paginates_without_city(monkeypatch):
    calls: list[int] = []

    def fake_request(client, method, url, **kwargs):
        assert url.endswith("/getPostListNew")
        page = int(kwargs["data"]["curPage"])
        calls.append(page)
        count = 20 if page == 1 else 5
        rows = [
            {
                "postId": f"b{page}-{index}",
                "name": f"AI 岗位 {page}-{index}",
                "workPlace": "北京市",
                "bgShortName": "MEG",
            }
            for index in range(count)
        ]
        return {
            "status": "ok",
            "data": {"hasNextPage": page == 1, "list": rows},
        }

    monkeypatch.setattr(baidu, "request_json", fake_request)
    rows = baidu.Scraper().search(keyword="AI", scope="social", limit=25)

    assert calls == [1, 2]
    assert len(rows) == 25


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
# 小红书
# ---------------------------------------------------------------------------


def test_xiaohongshu_search_and_detail(monkeypatch):
    payload = {
        "statusCode": 200,
        "data": {
            "totalPage": 1,
            "list": [
                {
                    "positionId": 18987,
                    "positionName": "Java后端开发工程师",
                    "workplace": "北京市，上海市",
                    "duty": "负责企业级平台研发",
                    "qualification": "熟悉 Java",
                    "jobType": "基础后端",
                    "directionName": "研发",
                    "publishTime": "2026-09-12",
                }
            ],
        },
    }
    monkeypatch.setattr(xiaohongshu, "request_json", lambda *a, **k: payload)
    scraper = xiaohongshu.Scraper()

    rows = scraper.search(keyword="Java", city="上海", limit=1)
    assert rows[0]["title"] == "Java后端开发工程师"
    assert rows[0]["location"] == "北京市，上海市"
    assert rows[0]["url"].endswith("/18987")

    detail = scraper.get_detail(rows[0]["url"])
    assert "负责企业级平台研发" in detail["description"]
    assert detail["company"] == "小红书"


# ---------------------------------------------------------------------------
# 滴滴
# ---------------------------------------------------------------------------


def test_didi_search_and_detail(monkeypatch):
    payload = {
        "meta": {"code": 0},
        "data": {
            "total": 1,
            "items": [
                {
                    "jdId": 66786,
                    "jobName": "AI Agent 开发工程师",
                    "workArea": "北京市",
                    "deptName": "Food Tech",
                    "jobDuty": "负责 Agent 架构",
                    "jobQualification": "熟悉 LangChain",
                    "jobTypeName": "技术",
                    "refreshTime": "2026-11-05",
                }
            ],
        },
    }
    monkeypatch.setattr(didi, "request_json", lambda *a, **k: payload)
    scraper = didi.Scraper()

    rows = scraper.search(keyword="Agent", city="北京", limit=1)
    assert rows[0]["title"] == "AI Agent 开发工程师"
    assert rows[0]["url"].endswith("/66786")

    detail = scraper.get_detail(rows[0]["url"])
    assert "负责 Agent 架构" in detail["description"]
    assert detail["company"] == "滴滴"


# ---------------------------------------------------------------------------
# 小米
# ---------------------------------------------------------------------------


def test_xiaomi_search_and_detail(monkeypatch):
    payload = {
        "code": 0,
        "data": {
            "list": [
                {
                    "title": "JAVA开发工程师",
                    "cityZhNames": ["武汉"],
                    "levelOneDeptName": "集团信息技术部",
                    "description": "参与物料系统开发",
                    "requirement": "熟悉 Java",
                    "publishTime": "2026-10-26",
                    "url": "https://xiaomi.jobs.f.mioffice.cn/index/position/7678236665135745286/detail",
                    "jobPostId": "7678236665135745286",
                    "jobId": "7678236665135630598",
                    "id": 475168,
                }
            ]
        },
    }
    monkeypatch.setattr(xiaomi, "request_json", lambda *a, **k: payload)
    scraper = xiaomi.Scraper()

    rows = scraper.search(keyword="Java", city="武汉", limit=1)
    assert rows[0]["title"] == "JAVA开发工程师"
    assert rows[0]["location"] == "武汉"
    assert rows[0]["url"].endswith("/detail")

    detail = scraper.get_detail(rows[0]["url"])
    assert "参与物料系统开发" in detail["description"]
    assert detail["company"] == "小米"


# ---------------------------------------------------------------------------
# 携程
# ---------------------------------------------------------------------------


def test_ctrip_search_and_detail(monkeypatch):
    payload = {
        "retCode": "201",
        "retValue": {
            "total": 1,
            "recruitJobAdList": [
                {
                    "jobId": "8917cb97-270b-441a-829d-6209a40dd402",
                    "fromId": "MJ037750",
                    "jobTitle": "景玩项目经理",
                    "cityName": "上海",
                    "requirements": "<p>熟悉项目管理</p>",
                    "duty": "<p>负责项目交付</p>",
                    "publishDate": "2026-11-05",
                }
            ],
        },
    }
    monkeypatch.setattr(ctrip, "request_json", lambda *a, **k: payload)
    scraper = ctrip.Scraper()

    rows = scraper.search(keyword="项目", city="上海", limit=1)
    assert rows[0]["title"] == "景玩项目经理"
    assert rows[0]["location"] == "上海"
    assert "jobId=8917" in rows[0]["url"]

    detail = scraper.get_detail(rows[0]["url"])
    assert "负责项目交付" in detail["description"]
    assert detail["company"] == "携程"


# ---------------------------------------------------------------------------
# 阿里巴巴（社招）
# ---------------------------------------------------------------------------


def test_alibaba_social_search_and_detail(monkeypatch):
    payload = {
        "success": True,
        "content": {
            "totalCount": 1,
            "datas": [
                {
                    "id": 100034220002,
                    "name": "鹿鸣工作室-服务器开发-java",
                    "workLocations": ["苏州"],
                    "categories": ["技术类"],
                    "description": "负责游戏服务端",
                    "requirement": "熟悉 Java",
                    "experience": {"from": 3, "to": 5},
                    "publishTime": 1787383311000,
                }
            ],
        },
    }
    monkeypatch.setattr(alibaba_social, "request_json", lambda *a, **k: payload)
    scraper = alibaba_social.Scraper()

    rows = scraper.search(keyword="Java", city="苏州", limit=1)
    assert rows[0]["title"] == "鹿鸣工作室-服务器开发-java"
    assert rows[0]["experience"] == "3-5年"
    assert "positionId=100034220002" in rows[0]["url"]

    detail = scraper.get_detail(rows[0]["url"])
    assert "负责游戏服务端" in detail["description"]
    assert detail["company"] == "阿里巴巴"


# ---------------------------------------------------------------------------
# 蚂蚁集团 / 哔哩哔哩（解析层）
# ---------------------------------------------------------------------------


def test_ant_format_and_detail_fallback():
    scraper = ant.Scraper()
    row = {
        "id": 261020012485394,
        "name": "蚂蚁国际-卡组计费管理与运营",
        "workLocations": ["上海", "杭州"],
        "categories": ["综合类-财务及内控"],
        "description": "负责卡组计费",
        "requirement": "熟悉财务",
        "publishTime": "2026-11-05T12:14:56.000+00:00",
    }
    item = scraper._format_post(row)
    assert item["title"] == "蚂蚁国际-卡组计费管理与运营"
    assert item["location"] == "上海/杭州"
    assert "positionId=261020012485394" in item["url"]
    assert ant._find_cookie([{"name": "ctoken", "value": "abc"}], "ctoken") == "abc"


def test_bilibili_parse_payload_and_detail():
    payload = {
        "data": {
            "list": [
                {
                    "id": 31092,
                    "positionName": "直播生态治理策略",
                    "positionDescription": "负责直播内容治理",
                    "positionTypeName": "全职",
                    "postCodeName": "产品运营类",
                    "pushTime": "2026-11-03",
                    "workLocation": "上海",
                }
            ]
        }
    }
    scraper = bilibili.Scraper()
    rows = scraper._parse_payload(payload, city="上海", limit=1)
    assert rows[0]["title"] == "直播生态治理策略"
    assert rows[0]["url"].endswith("/31092")

    detail = scraper.get_detail(rows[0]["url"])
    assert detail["description"] == "负责直播内容治理"
    assert detail["company"] == "哔哩哔哩"


# ---------------------------------------------------------------------------
# 北森平台（京东方 / 三一 / 汇川）
# ---------------------------------------------------------------------------


def test_beisen_search_and_detail(monkeypatch):
    payload = {
        "Code": 200,
        "Count": 2,
        "Data": [
            {
                "Id": "beisen-1",
                "JobAdName": "算法工程师",
                "LocNames": ["北京市·大兴区"],
                "Org": "集团研发",
                "Duty": "负责算法研发",
                "Require": "熟悉 Python",
                "Salary": None,
            },
            {
                "Id": "beisen-2",
                "JobAdName": "工艺工程师",
                "LocNames": ["合肥市"],
                "Org": "制造体系",
                "Duty": "负责工艺设计",
                "Require": "熟悉机械",
                "Salary": None,
            },
        ],
    }
    monkeypatch.setattr(beisen_platform, "request_json", lambda *a, **k: payload)
    scraper = boe.Scraper()

    rows = scraper.search(keyword="算法", city="北京", limit=2)
    assert len(rows) == 1
    assert rows[0]["title"] == "算法工程师"
    assert rows[0]["location"] == "北京市·大兴区"
    assert rows[0]["department"] == "集团研发"
    assert "jobAdId=beisen-1" in rows[0]["url"]

    detail = scraper.get_detail(rows[0]["url"])
    assert detail["description"] == "负责算法研发"
    assert detail["requirements"] == "熟悉 Python"
    assert detail["company"] == "京东方"


# ---------------------------------------------------------------------------
# 大易平台（中国中车 / 中联重科 / 特变电工）
# ---------------------------------------------------------------------------


def test_dayee_search_and_detail(monkeypatch):
    def fake_request(client, method, url, **kwargs):
        if "listPositionDetail" in url:
            return {
                "state": "200",
                "data": {
                    "postName": "电气工程师",
                    "workPlaceStr": "南京市",
                    "company": "中车南京浦镇车辆有限公司",
                    "orgName": "中车南京浦镇车辆有限公司",
                    "workContent": "负责电气系统设计",
                    "serviceCondition": "熟悉电气原理",
                    "education": "本科及以上",
                    "postTypeName": "电气、自动化类",
                    "publishDate": "2026-10-09",
                },
            }
        return {
            "state": "200",
            "data": {
                "pageForm": {
                    "totalPage": 1,
                    "pageData": [
                        {
                            "postId": "dayee-1",
                            "postName": "电气工程师",
                            "workPlaceStr": "南京市",
                            "company": "中车南京浦镇车辆有限公司",
                            "postType": "0/1227/103401",
                            "postTypeName": "电气、自动化类",
                            "educationStr": "本科及以上",
                            "publishDate": "2026-10-09",
                        }
                    ],
                }
            },
        }

    monkeypatch.setattr(dayee_platform, "request_json", fake_request)
    scraper = crrc.Scraper()

    rows = scraper.search(keyword="电气", city="南京", limit=1)
    assert rows[0]["title"] == "电气工程师"
    assert rows[0]["location"] == "南京市"
    assert "postId=dayee-1" in rows[0]["url"]

    detail = scraper.get_detail(rows[0]["url"])
    assert detail["description"] == "负责电气系统设计"
    assert detail["requirements"] == "熟悉电气原理"
    assert detail["company"] == "中国中车"


def test_dayee_suite_key_routing():
    assert zhonglian.Scraper().supports_url(
        "https://wecruit.hotjob.cn/SU60a6449a2f9d2430fdc11a19/pb/posDetail.html?postId=1"
    )
    assert not zhonglian.Scraper().supports_url(
        "https://wecruit.hotjob.cn/SU612f55eebef57c0616450aa2/pb/posDetail.html?postId=1"
    )
    assert tebian.Scraper().supports_url(
        "https://wecruit.hotjob.cn/SU612f55eebef57c0616450aa2/pb/posDetail.html?postId=1"
    )


# ---------------------------------------------------------------------------
# Moka 平台（阳光电源）
# ---------------------------------------------------------------------------


def _moka_encrypt(payload: dict, key: bytes, iv: bytes) -> dict:
    plain = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    padder = PKCS7(128).padder()
    padded = padder.update(plain) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    cipher = encryptor.update(padded) + encryptor.finalize()
    return {
        "necromancer": key.decode("utf-8"),
        "data": base64.b64encode(cipher).decode("utf-8"),
    }


def test_moka_decrypt_and_search(monkeypatch):
    key = b"0123456789abcdef"
    iv = b"fedcba9876543210"

    def fake_request(client, method, url, **kwargs):
        if url.endswith("/website/job"):
            return _moka_encrypt(
                {
                    "code": 0,
                    "data": {
                        "id": "moka-1",
                        "title": "硬件工程师",
                        "commitment": "全职",
                        "locations": [{"cityName": "合肥市"}],
                        "jobDescription": "<p>负责硬件设计</p><p>二、任职要求</p><p>熟悉电源拓扑</p>",
                    },
                },
                key,
                iv,
            )
        return _moka_encrypt(
            {
                "code": 0,
                "data": {
                    "jobStats": {"total": 1},
                    "jobs": [
                        {
                            "id": "moka-1",
                            "title": "硬件工程师",
                            "locations": [{"cityName": "合肥市"}],
                        }
                    ],
                },
            },
            key,
            iv,
        )

    monkeypatch.setattr(moka_platform, "request_json", fake_request)
    monkeypatch.setattr(
        moka_platform.MokaScraper, "_fetch_aes_iv", lambda self, client: iv
    )
    scraper = sungrow.Scraper()

    rows = scraper.search(keyword="硬件", city="合肥", limit=1)
    assert rows[0]["title"] == "硬件工程师"
    assert rows[0]["location"] == "合肥市"
    assert rows[0]["url"].endswith("#/job/moka-1")

    detail = scraper.get_detail(rows[0]["url"])
    assert detail["description"] == "负责硬件设计"
    assert detail["requirements"] == "熟悉电源拓扑"
    assert detail["company"] == "阳光电源"


# ---------------------------------------------------------------------------
# 华为
# ---------------------------------------------------------------------------


def test_huawei_search_and_detail(monkeypatch):
    payload = {
        "status": "SUCCESS",
        "data": {
            "pageVO": {"totalPages": 1},
            "result": [
                {
                    "jobId": 114740,
                    "jobName": "IT平台首席AI架构师",
                    "workPlace": "深圳",
                    "deptName": "质量与流程IT部",
                    "jobFamilyName": "质量与流程IT族",
                    "workYear": "5",
                    "lastUpdateDate": "2026-10-16",
                    "mainBusiness": "负责 AI 架构设计",
                    "jobRequire": "熟悉 AI 技术",
                }
            ],
        },
    }
    monkeypatch.setattr(huawei, "request_json", lambda *a, **k: payload)
    scraper = huawei.Scraper()

    rows = scraper.search(keyword="AI", city="深圳", limit=1)
    assert rows[0]["title"] == "IT平台首席AI架构师"
    assert rows[0]["location"] == "深圳"
    assert "jobId=114740" in rows[0]["url"]

    detail = scraper.get_detail(rows[0]["url"])
    assert detail["description"] == "负责 AI 架构设计"
    assert detail["requirements"] == "熟悉 AI 技术"
    assert detail["company"] == "华为"


# ---------------------------------------------------------------------------
# 注册与路由
# ---------------------------------------------------------------------------


def test_new_scrapers_registered_with_params():
    by_id = {s["id"]: s for s in list_scrapers()}
    for cid in (
        "tencent",
        "baidu",
        "alibaba",
        "meituan",
        "netease",
        "jd",
        "kuaishou",
        "pdd",
        "xiaohongshu",
        "didi",
        "ant",
        "ctrip",
        "bilibili",
        "xiaomi",
        "alibaba_social",
        "boe",
        "huawei",
        "sany",
        "crrc",
        "zhonglian",
        "inovance",
        "tebian",
        "sungrow",
    ):
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
        "https://job.xiaohongshu.com/social/position/1": "xiaohongshu",
        "https://talent.didiglobal.com/social/p/1": "didi",
        "https://talent.antgroup.com/off-campus-position?positionId=1": "ant",
        "https://careers.ctrip.com/#/experienced/jobDetail?jobId=1": "ctrip",
        "https://jobs.bilibili.com/social/positions/1": "bilibili",
        "https://hr.xiaomi.com/website/opportunities.html?jobId=1": "xiaomi",
        "https://talent.alibaba.com/off-campus/position-detail?positionId=1": "alibaba_social",
        "https://boe.zhiye.com/social/jobs?jobAdId=1": "boe",
        "https://career.huawei.com/cn/social-recruitment-job-list?jobId=1": "huawei",
        "https://sany.zhiye.com/social/jobs?jobAdId=1": "sany",
        "https://crrc.hotjob.cn/SU64d47c466202cc36e27a52d4/pb/posDetail.html?postId=1": "crrc",
        "https://wecruit.hotjob.cn/SU60a6449a2f9d2430fdc11a19/pb/posDetail.html?postId=1": "zhonglian",
        "https://inovance.zhiye.com/social/jobs?jobAdId=1": "inovance",
        "https://wecruit.hotjob.cn/SU612f55eebef57c0616450aa2/pb/posDetail.html?postId=1": "tebian",
        "https://app.mokahr.com/social-recruitment/sungrow/94415#/job/1": "sungrow",
    }
    for url, expected in cases.items():
        scraper = get_scraper_for_url(url)
        assert scraper is not None and expected == scraper.COMPANY_SLUG
