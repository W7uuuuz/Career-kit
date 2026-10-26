"""BUG 修复第四轮：批量调研时 bytedance 20s 超时（单独调用成功）。

根因：Playwright 首页热身 goto 超时（20s）会直接终止整次抓取——批量调研时
Edge 冷启动/站点波动更慢，于是比单独调用更容易命中。修复后：
- 首页热身 = 尽力而为，失败继续走搜索页（数据来自搜索页 XHR）；
- 搜索页导航超时重试一次；
- 浏览器在异常路径也确保关闭。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding="utf-8")


class _FakePage:
    def __init__(self, failures: int = 0):
        self.failures = failures
        self.calls: list[str] = []
        self.waits = 0

    def goto(self, url: str, **_kwargs):
        self.calls.append(url)
        if self.failures > 0:
            self.failures -= 1
            raise TimeoutError("Timeout 20000ms exceeded")
        return None

    def wait_for_timeout(self, _ms: int):
        self.waits += 1


def test_bytedance_goto_retries_once_after_timeout():
    from src.scrapers.bytedance.scraper import Scraper

    page = _FakePage(failures=1)
    Scraper._goto_with_retry(page, "https://jobs.bytedance.com/search")
    assert len(page.calls) == 2, "首次导航超时应重试一次"
    assert page.waits >= 1


def test_bytedance_goto_raises_after_retries_exhausted():
    from src.scrapers.bytedance.scraper import Scraper

    page = _FakePage(failures=2)
    try:
        Scraper._goto_with_retry(page, "https://jobs.bytedance.com/search")
    except TimeoutError:
        pass
    else:
        raise AssertionError("两次都超时应抛出最后错误，交给上层如实上报")
    assert len(page.calls) == 2


def test_bytedance_home_warmup_failure_never_blocks():
    from src.scrapers.bytedance.scraper import Scraper

    page = _FakePage(failures=1)
    Scraper._warm_up_page(page)  # 不抛异常
    assert len(page.calls) == 1
