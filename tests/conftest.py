"""共享 fixtures：隔离用户真实目录的 Hook。

autouse：本目录（含 e2e）任何测试都不落盘到真实 ~/CareerKit，
统一把资产根指向本次测试的临时目录（src.assets.get_assets_root 每次读取环境变量）。
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _career_kit_assets_sandbox(tmp_path, monkeypatch):
    monkeypatch.setenv("CAREER_KIT_ASSETS_DIR", str(tmp_path / "CareerKit"))
    yield
