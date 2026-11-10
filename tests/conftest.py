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


@pytest.fixture(autouse=True)
def _career_kit_data_sandbox(tmp_path, monkeypatch):
    """所有单测的档案与 artifact 数据库都落临时目录，避免真实数据互相污染。"""
    from src import paths
    from src.tools import profile as profile_store

    data = tmp_path / "career-data"
    monkeypatch.setattr(paths, "PROFILE_DIR", data)
    monkeypatch.setattr(profile_store, "PROFILE_DIR", data)
    yield


def promote_profile(
    profile,
    profile_name="",
    *,
    execution=False,
    detail=False,
    company=False,
):
    """把测试档案提升为状态机可调用的真实链路（ProfileSnapshot + TargetSpec）。"""
    from src.core import sync
    from src.guidance import mark_goal_confirmed
    from src.tools.profile import get_active_profile_name, load_profile, save_profile

    profile_name = profile_name or get_active_profile_name()

    if not profile.who:
        profile.who = {"name": "测试用户"}
    if not profile.have:
        profile.have = {"skills": ["Python"]}
    if not profile.want:
        profile.want = {"target_role": "AI Agent 开发"}
    mark_goal_confirmed(profile)
    if not profile.gap:
        profile.gap = {"match_score": 50}
    if execution or company:
        plan = profile.plan if isinstance(profile.plan, dict) else {}
        if not plan.get("roadmap"):
            plan["roadmap"] = {
                "phases": [
                    {
                        "id": "phase_1",
                        "name": "阶段",
                        "milestones": [
                            {"id": "m1", "name": "M1", "tasks": [{"name": "任务A"}]}
                        ],
                    }
                ]
            }
        if detail:
            plan["current_detail"] = {
                "phase_id": "phase_1",
                "tasks": [{"name": "任务A"}],
            }
        profile.plan = plan
        if execution:
            guidance = dict(profile.guidance or {})
            guidance["enterprise_alignment_skipped_at"] = "2026-11-10T00:00:00"
            profile.guidance = guidance
    save_profile(profile, profile_name)
    sync.sync_profile(profile_name)
    sync.sync_target(profile_name)
    return load_profile(profile_name)


def seed_baseline_pool(profile_name="", *, pool_id="cp_test", baseline_id="bp_test"):
    """Seed 一个可引用的 BaselinePlan + 已确认 CompanyPool，供企业链路状态 fixture 使用。"""
    from datetime import datetime

    from src.core.artifacts.models import (
        ArtifactMeta,
        BaselinePlan,
        CompanyEntry,
        CompanyPool,
        TargetSpec,
    )
    from src.core.artifacts.store import ArtifactStore

    store = ArtifactStore()
    store.save(
        BaselinePlan(
            meta=ArtifactMeta(
                id=baseline_id,
                stage="baseline_plan",
                profile_name=profile_name,
                created_at=datetime.now().isoformat(),
            ),
            gap_report_id="gr_state_test",
            roadmap={"phases": [{"id": "phase_1", "name": "基础"}]},
        )
    )
    store.save(
        CompanyPool(
            meta=ArtifactMeta(
                id=pool_id,
                stage="company_pool",
                profile_name=profile_name,
                created_at=datetime.now().isoformat(),
                inputs={"baseline_plan_id": baseline_id},
                validation={"confirmed": True},
            ),
            target_spec=TargetSpec(role="AI Agent 开发"),
            companies=[
                CompanyEntry(
                    id="bytedance",
                    name="字节跳动",
                    tier="大厂",
                    industry="互联网",
                    scrapable=True,
                    status="confirmed",
                )
            ],
        )
    )
    return baseline_id, pool_id
