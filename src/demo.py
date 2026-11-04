"""零安装演示：打开随包附带的交互式职业地图。

用法：
    career-kit-demo
    career-kit-demo --no-open

演示产物由 `docs/examples/build_demo.py` 用真实管线生成，随 wheel 一起分发；
离线打开时打卡写入浏览器 localStorage，不会修改用户档案。
"""

from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path


def demo_html() -> Path | None:
    """定位随包附带的示例职业地图；找不到返回 None。"""
    here = Path(__file__).resolve()
    # editable 安装：repo/src/demo.py → repo/docs/...
    # wheel 安装：site-packages/src/demo.py → site-packages/docs/...
    roots = (here.parent.parent, here.parent)
    for root in roots:
        target = root / "docs" / "examples" / "demo" / "career-map.html"
        if target.is_file():
            return target
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="打开 Career Kit 示例职业地图（无需安装与配置）"
    )
    parser.add_argument(
        "--no-open", action="store_true", help="只打印文件路径，不打开浏览器"
    )
    args = parser.parse_args(argv)

    target = demo_html()
    if target is None:
        print(
            "未找到示例文件。请从仓库 docs/examples/demo/ 打开，"
            "或运行 career-kit-serve 查看你自己的档案。",
            file=sys.stderr,
        )
        return 1

    print(f"Career Kit 示例职业地图：{target}")
    print("这是离线演示：勾选任务会把进度保存在当前浏览器，不会修改你的档案。")
    if not args.no_open:
        webbrowser.open(target.as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
