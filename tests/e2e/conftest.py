"""E2E 全局开关、隔离沙箱与产物管理。"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

E2E_DIR = Path(__file__).resolve().parent
TESTS_DIR = E2E_DIR.parent
REPO_ROOT = TESTS_DIR.parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

# 默认单测不收集 E2E；显式设 CAREER_KIT_E2E=1 或使用 cli.py 才运行。
if not os.environ.get("CAREER_KIT_E2E"):
    collect_ignore_glob = ["*"]

from e2e.harness import QualityRecorder, Sandbox  # noqa: E402


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    setattr(item, f"rep_{report.when}", report)


@pytest.fixture(scope="session")
def run_root() -> Path:
    configured = os.environ.get("CAREER_KIT_E2E_ARTIFACTS")
    if configured:
        root = Path(configured)
    else:
        root = REPO_ROOT / "artifacts" / "e2e" / time.strftime("%Y%m%d-%H%M%S")
    root.mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture()
def sandbox(request, run_root) -> Sandbox:
    box = Sandbox.create(request.node.name, run_root)
    yield box
    report = getattr(request.node, "rep_call", None)
    box.finalize(bool(report and report.failed))


@pytest.fixture()
def quality(sandbox: Sandbox) -> QualityRecorder:
    return QualityRecorder(sandbox)
