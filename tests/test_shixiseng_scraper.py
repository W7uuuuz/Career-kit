"""实习僧 scraper 离线解析回归（不访问真实站点）。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import src.scrapers.base as base
import src.scrapers.shixiseng.scraper as shixiseng


@pytest.fixture(autouse=True)
def _isolate_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(base, "CACHE_DIR", tmp_path)


SEARCH_HTML = """
<div data-intern-id="inn_alpha" class="intern-wrap">
  <div class="clearfix intern-detail">
    <div class="f-l intern-detail__job">
      <p><a href="https://www.shixiseng.com/intern/inn_alpha?pcm=pc_SearchList"
            class="title ellipsis font">量化研究实习&#xf134</a>
      <span class="day font">200-300/天</span></p>
      <p class="tip"><span class="city ellipsis">上海</span><span>|</span></p>
    </div>
    <div class="f-r intern-detail__company">
      <p><a title="测试资产" href="javascript:;" class="title ellipsis">测试资产</a></p>
      <p class="tip"><span class="ellipsis">金融/经济/投资/财会</span></p>
    </div>
  </div>
</div>
<div data-intern-id="inn_beta" class="intern-wrap">
  <div class="clearfix intern-detail">
    <div class="f-l intern-detail__job">
      <p><a href="https://www.shixiseng.com/intern/inn_beta?pcm=pc_SearchList"
            class="title ellipsis font">行业研究实习生</a>
      <span class="day font">&#xf466&#xf2f6&#xf2f6/天</span></p>
      <p class="tip"><span class="city ellipsis">北京</span><span>|</span></p>
    </div>
    <div class="f-r intern-detail__company">
      <p><a title="测试证券" href="javascript:;" class="title ellipsis">测试证券</a></p>
      <p class="tip"><span class="ellipsis">证券/投资</span></p>
    </div>
  </div>
</div>
"""

NUXT_HTML = """
<html><body><script>
window.__NUXT__=(function(a,b,c,d,e,f,g,h,i,j){return {layout:"default",data:[{interns:{data:[
{ad_type:f,maxsal:j,minasal:j,name:"后&#xf0b6开发",cname:"测试公司",city:d,industry:e,minsalary:j,maxsalary:b,degree:i,uuid:"inn_nuxt1",i_tags:["Java","MySQL"]},
{ad_type:f,maxsal:b,minasal:j,name:"量化实习",cname:"测试二号",city:d,industry:e,minsalary:200,maxsalary:300,degree:i,uuid:"inn_nuxt2",i_tags:[]}
]}}]}})(false,300,"","北京","互联网/游戏/软件","f",true,false,"本科",200);
</script></body></html>
"""

DETAIL_HTML = """
<div class="intern-detail-page">
  <div class="job-box">
    <div class="job-header">
      <div class="new_job_name"><span>量化研究实习生</span></div>
      <div class="job_date"><span class="cutom_font">2026-11-10 12:00:00</span><span>刷新</span></div>
      <div class="job_msg">
        <span class="job_money cutom_font">1000-1800/天</span>
        <span title="上海" class="job_position">上海</span>
        <span class="job_academic">硕士</span>
      </div>
      <div class="job_good_list"><span>周末双休</span><span>导师带教</span></div>
    </div>
    <div class="job-content">
      <div class="con-job">
        <div class="job_til">职位描述</div>
        <div class="job_detail">岗位职责
1. 做因子研究与回测
2. 跟踪策略表现</div>
      </div>
      <div class="con-job">
        <div class="job_til">投递要求</div>
        <div>学历要求：本科</div>
        <div>截止日期：2026-12-01</div>
      </div>
      <div class="con-job job_city">
        <span class="com_position">上海市/浦东新区</span>
      </div>
    </div>
    <a href="javascript:;" class="com-name com-name--with-label">测试资产</a>
  </div>
</div>
"""


def test_search_parses_cards(monkeypatch):
    captured: dict[str, object] = {}

    def fake_fetch(url, params):
        captured["url"] = url
        captured["params"] = params
        return SEARCH_HTML

    monkeypatch.setattr(shixiseng, "_fetch_html", fake_fetch)
    rows = shixiseng.Scraper().search(keyword="量化", city="上海", limit=2)

    assert len(rows) == 2
    first = rows[0]
    assert first["title"] == "量化研究实习生"
    assert first["company"] == "测试资产"
    assert first["location"] == "上海"
    assert first["salary"] == "200-300/天"
    assert first["department"] == "金融/经济/投资/财会"
    assert first["url"] == "https://www.shixiseng.com/intern/inn_alpha"
    assert first["job_type"] == "实习"
    assert first["source"] == "shixiseng"

    # 私有区数字按公开字体映射还原
    assert rows[1]["salary"] == "200/天"
    assert captured["params"]["publishTime"] == "mon"
    assert captured["params"]["city"] == "上海"


def test_search_prefers_nuxt_structured_data(monkeypatch):
    monkeypatch.setattr(shixiseng, "_fetch_html", lambda url, params: NUXT_HTML)
    rows = shixiseng.Scraper().search(keyword="后端", city="北京", limit=5)

    assert len(rows) == 2
    first = rows[0]
    # 标题中的私有区字符按字体映射还原；薪资与标签来自 Nuxt 明文数据
    assert first["title"] == "后端开发"
    assert first["company"] == "测试公司"
    assert first["salary"] == "200-300/天"
    assert first["degree"] == "本科"
    assert first["tags"] == ["Java", "MySQL"]
    assert "学历：本科" in first["summary"]
    assert "标签：Java、MySQL" in first["summary"]
    assert rows[1]["salary"] == "200-300/天"


def test_unknown_private_use_char_is_stripped():
    assert shixiseng._clean_text("后\ue000开发") == "后开发"
    assert shixiseng._clean_text("后\uf0b6开发") == "后端开发"


def test_search_requires_keyword():
    rows = shixiseng.Scraper().search(keyword="")
    assert rows and rows[0].get("error")


def test_search_empty_reports_honestly(monkeypatch):
    monkeypatch.setattr(shixiseng, "_fetch_html", lambda url, params: "<html></html>")
    rows = shixiseng.Scraper().search(keyword="不存在的方向")
    assert rows and rows[0].get("error")
    assert "未找到" in rows[0]["error"]


def test_detail_parses_description_and_requirements(monkeypatch):
    monkeypatch.setattr(shixiseng, "_fetch_html", lambda url, params: DETAIL_HTML)
    detail = shixiseng.Scraper().get_detail(
        "https://www.shixiseng.com/intern/inn_alpha?pcm=pc_SearchList"
    )

    assert detail["title"] == "量化研究实习生"
    assert detail["company"] == "测试资产"
    assert detail["location"] == "上海"
    assert detail["address"] == "上海市/浦东新区"
    assert detail["salary"] == "1000-1800/天"
    assert detail["degree"] == "硕士"
    assert "做因子研究与回测" in detail["description"]
    assert "学历要求：本科" in detail["requirements"]
    assert "截止日期：2026-12-01" in detail["requirements"]
    assert detail["benefits"] == "周末双休、导师带教"
    assert detail["updated_at"] == "2026-11-10 12:00:00"


def test_detail_falls_back_to_list_snapshot(monkeypatch):
    scraper = shixiseng.Scraper()
    monkeypatch.setattr(shixiseng, "_fetch_html", lambda url, params: SEARCH_HTML)
    rows = scraper.search(keyword="量化", city="上海", limit=1)

    monkeypatch.setattr(
        shixiseng, "_fetch_html", lambda url, params: "<html><body>登录后查看</body></html>"
    )
    detail = scraper.get_detail(rows[0]["url"])

    assert detail["title"] == rows[0]["title"]
    assert detail["company"] == rows[0]["company"]
    assert detail["_note"]
