"""阶段 6 目标企业筛选回归——目录筛选、include/exclude、可抓标记与确认门禁。"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src import paths
from src.core.artifacts.models import ArtifactMeta, CompanyPool, TargetSpec
from src.core.artifacts.store import ArtifactStore
from src.core.orchestrator import state_machine
from src.core.stages import target_companies
from src.core.stages.base import StageContext, StageResult
from src.scrapers import catalog
from src.tools import profile as profile_module
from src.tools.company_selection_tools import select_target_companies


class _TargetArtifact(TargetSpec):
    """测试用 TargetSpec + meta，用于验证 target_spec_id 解析。"""

    meta: ArtifactMeta


def _save_target(
    store: ArtifactStore, profile_name: str, role: str = "AI Agent 开发"
) -> str:
    artifact = _TargetArtifact(
        meta=ArtifactMeta(
            id=store.new_id("ts_"),
            stage=state_machine.STAGE_TARGET,
            profile_name=profile_name,
            created_at="2026-01-01T00:00:00",
        ),
        role=role,
    )
    return store.save(artifact)


@pytest.fixture()
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "data"
    monkeypatch.setattr(paths, "PROFILE_DIR", root)
    monkeypatch.setattr(profile_module, "PROFILE_DIR", root)
    catalog.reload_catalog()
    return root


def _run(
    store: ArtifactStore,
    inputs: dict[str, Any],
    confirmed: bool = False,
    profile_name: str = "default",
) -> tuple[StageResult, dict[str, Any]]:
    ctx = StageContext(profile_name=profile_name, store=store, user_confirmed=confirmed)
    result = target_companies.run(ctx, inputs)
    artifact = store.load(result.artifact_id)
    assert artifact is not None
    return result, artifact


def test_recommended_mode_saves_artifact_and_keeps_gate(data_dir: Path) -> None:
    store = ArtifactStore()
    result, artifact = _run(store, {"target_spec": {"role": "AI Agent 开发", "city": "北京"}})

    assert result.status == "needs_confirmation"
    assert artifact["meta"]["stage"] == state_machine.STAGE_COMPANY_POOL
    assert artifact["meta"]["validation"]["confirmed"] is False
    assert artifact["target_spec"]["role"] == "AI Agent 开发"
    assert artifact["target_spec"]["city"] == "北京"
    assert artifact["companies"]
    assert all(item["status"] == "recommended" for item in artifact["companies"])
    assert artifact["counts"]["total"] == len(artifact["companies"])
    assert target_companies.validate(CompanyPool.model_validate(artifact)) == []

    action = state_machine.next_action("default")
    assert action["next_tool"] == "select_target_companies"
    assert action["stage"] == state_machine.STAGE_COMPANY_POOL


def test_confirmed_mode_writes_core_state_and_unlocks_evidence(data_dir: Path) -> None:
    store = ArtifactStore()
    result, artifact = _run(
        store,
        {"target_spec": {"role": "AI Agent 开发"}, "confirmed": True},
    )

    assert result.status == "ok"
    assert result.next_stage == state_machine.STAGE_EVIDENCE
    assert artifact["meta"]["validation"]["confirmed"] is True
    assert artifact["companies"]
    assert all(item["status"] == "confirmed" for item in artifact["companies"])

    profile = profile_module.load_profile("default")
    assert profile.core_state["company_pool_id"] == result.artifact_id
    assert profile.core_state["stage"] == state_machine.STAGE_COMPANY_POOL
    assert profile.core_state["updated_at"]

    action = state_machine.next_action("default")
    assert action["next_tool"] == "collect_company_evidence"
    assert action["artifact_ids"]["company_pool_id"] == result.artifact_id


def test_meta_inputs_include_target_spec_id(data_dir: Path) -> None:
    store = ArtifactStore()
    _, artifact = _run(store, {"target_spec": {"role": "AI Agent 开发"}})

    inputs = artifact["meta"]["inputs"]
    assert "target_spec_id" in inputs
    assert inputs["target_spec_id"] == ""


def test_meta_inputs_use_core_state_target_spec_id(data_dir: Path) -> None:
    store = ArtifactStore()
    core_id = _save_target(store, "default", role="档案目标")
    newest_id = _save_target(store, "default", role="新目标")
    profile = profile_module.load_profile("default")
    profile.core_state = {"target_spec_id": core_id}
    profile_module.save_profile(profile, "default")

    _, artifact = _run(store, {})

    assert artifact["meta"]["inputs"]["target_spec_id"] == core_id
    assert artifact["meta"]["inputs"]["target_spec_id"] != newest_id


def test_explicit_target_spec_from_other_profile_is_rejected(data_dir: Path) -> None:
    store = ArtifactStore()
    bob_id = _save_target(store, "bob")

    ctx = StageContext(profile_name="default", store=store)
    result = target_companies.run(ctx, {"target_spec_id": bob_id})

    assert result.status == "failed"
    assert "不属于当前档案" in result.message
    assert store.latest("default", state_machine.STAGE_COMPANY_POOL) is None


def test_confirmed_without_selected_companies_returns_insufficient_data(data_dir: Path) -> None:
    store = ArtifactStore()
    result, artifact = _run(
        store,
        {
            "target_tiers": "小厂",
            "bridge_tiers": "小厂",
            "industry": "不存在的行业",
            "confirmed": True,
        },
    )

    assert result.status == "insufficient_data"
    assert artifact["meta"]["validation"]["confirmed"] is False
    assert artifact["companies"] == []
    assert any("没有匹配" in gap for gap in artifact["gaps"])
    assert profile_module.load_profile("default").core_state == {}
    assert state_machine.next_action("default")["next_tool"] == "select_target_companies"


def test_include_json_adds_outside_filter_and_exclude_delimited(data_dir: Path) -> None:
    store = ArtifactStore()
    _, artifact = _run(
        store,
        {
            "target_tiers": "大厂",
            "bridge_tiers": "中厂",
            "industry": "互联网",
            "include": '["dewu", "华为"]',
            "exclude": "腾讯,美团",
        },
    )

    entries = {item["id"]: item for item in artifact["companies"]}
    assert entries["dewu"]["status"] == "recommended"
    assert entries["huawei"]["status"] == "recommended"
    assert entries["huawei"]["industry"] == "硬件/科技"
    assert entries["tencent"]["status"] == "excluded"
    assert entries["meituan"]["status"] == "excluded"
    assert artifact["counts"]["excluded"] == 2


def test_include_exclude_delimiters_unknown_report_and_include_priority(data_dir: Path) -> None:
    store = ArtifactStore()
    _, artifact = _run(
        store,
        {
            "target_tiers": "大厂、中厂",
            "industry": "互联网",
            "include": "dewu 米哈游 得物",
            "exclude": "百度，京东、不存在的公司",
        },
    )

    entries = {item["id"]: item for item in artifact["companies"]}
    assert entries["dewu"]["status"] == "recommended"
    assert entries["mihoyo"]["status"] == "recommended"
    assert entries["baidu"]["status"] == "excluded"
    assert entries["jd"]["status"] == "excluded"
    assert "用户 include" in entries["dewu"]["reason"]
    assert any("不存在的公司" in gap for gap in artifact["gaps"])


def test_unscrapable_companies_are_kept_with_flag(data_dir: Path) -> None:
    store = ArtifactStore()
    _, artifact = _run(store, {"target_tiers": "中厂", "industry": "互联网"})

    dewu = next(item for item in artifact["companies"] if item["id"] == "dewu")
    assert dewu["scrapable"] is False
    assert dewu["scrapers"] == []
    assert artifact["counts"]["not_scrapable"] > 0
    assert any("未接入自动抓取" in gap and "得物" in gap for gap in artifact["gaps"])


def test_select_target_companies_tool_recommended(data_dir: Path) -> None:
    payload = json.loads(select_target_companies(include="dewu"))

    assert payload["status"] == "needs_confirmation"
    assert payload["artifact_id"].startswith("cp_")
    assert payload["confirmed"] is False
    assert payload["next_tool"] == "select_target_companies"
    assert "大厂" in payload["by_tier"]
    assert "得物" in payload["not_scrapable"]
    assert payload["unscrapable_note"]

    stored = ArtifactStore().load(payload["artifact_id"])
    assert stored is not None
    assert stored["meta"]["validation"]["confirmed"] is False


def test_select_target_companies_tool_confirmed(data_dir: Path) -> None:
    payload = json.loads(
        select_target_companies(target_tiers="大厂", bridge_tiers="中厂", confirmed=True)
    )

    assert payload["status"] == "ok"
    assert payload["confirmed"] is True
    assert payload["next_tool"] == "collect_company_evidence"

    profile = profile_module.load_profile("default")
    assert profile.core_state["company_pool_id"] == payload["artifact_id"]
    assert state_machine.next_action("default")["next_tool"] == "collect_company_evidence"
