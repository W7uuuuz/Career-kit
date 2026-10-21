"""E2E 运行入口。

用法：
    python tests/e2e/cli.py --suite core
    python tests/e2e/cli.py --suite live --sources tencent,baidu,alibaba
    python tests/e2e/cli.py --suite browser
    python tests/e2e/cli.py --suite llm
    python tests/e2e/cli.py --suite all
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

MARKERS = {
    "core": "e2e and not e2e_live and not e2e_browser and not e2e_llm",
    "live": "e2e_live",
    "browser": "e2e_browser",
    "llm": "e2e_llm",
    "all": "e2e",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Career Kit E2E runner")
    parser.add_argument(
        "--suite",
        choices=sorted(MARKERS),
        default="core",
        help="要运行的套件（默认 core）",
    )
    parser.add_argument(
        "--sources",
        default="tencent,baidu,alibaba",
        help="live 套件的数据源，逗号分隔",
    )
    parser.add_argument("--keep", action="store_true", help="保留沙箱目录")
    parser.add_argument("--run-id", default="", help="自定义产物目录名")
    parser.add_argument("-v", "--verbose", action="store_true", help="显示详细输出")
    args = parser.parse_args()

    run_id = args.run_id or time.strftime("%Y%m%d-%H%M%S")
    run_root = REPO_ROOT / "artifacts" / "e2e" / run_id
    run_root.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ)
    env["CAREER_KIT_E2E"] = "1"
    env["CAREER_KIT_E2E_ARTIFACTS"] = str(run_root)
    env["CAREER_KIT_E2E_SOURCES"] = args.sources
    if args.keep:
        env["CAREER_KIT_E2E_KEEP"] = "1"
    if args.suite in ("live", "all", "core"):
        env.setdefault("CAREER_KIT_E2E_LIVE", "1" if args.suite in ("live", "all") else "0")
    if args.suite in ("browser", "all"):
        env["CAREER_KIT_E2E_BROWSER"] = "1"

    command = [
        sys.executable,
        "-m",
        "pytest",
        "tests/e2e",
        "-m",
        MARKERS[args.suite],
        "--junitxml",
        str(run_root / "junit.xml"),
    ]
    if args.verbose:
        command.append("-s")
    else:
        command.append("-q")

    print(f"[E2E] suite={args.suite} artifacts={run_root}")
    completed = subprocess.run(command, cwd=REPO_ROOT, env=env)
    print(f"[E2E] exit={completed.returncode}")
    if completed.returncode != 0:
        print(f"[E2E] 失败产物已保留：{run_root}")
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
