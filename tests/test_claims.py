"""结论引用记录：来源校验、从业者经验范围、持久化与查询。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

import pytest
import src.tools.profile as profile_module


@pytest.fixture()
def temp_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(profile_module, "PROFILE_DIR", tmp_path)
    monkeypatch.setenv("CAREER_KIT_ASSETS_DIR", str(tmp_path / "CareerKit"))
    return tmp_path


def _record(payload: dict):
    from src.server import record_claim

    return json.loads(record_claim(json.dumps(payload, ensure_ascii=False)))


def test_fact_requires_source(temp_profile):
    out = _record({"statement": "字节后端要求 RAG", "claim_type": "fact"})
    assert out["isError"] is True
    assert out["code"] == "INVALID_PARAM"


def test_practitioner_experience_requires_source_and_scope(temp_profile):
    out = _record({
        "statement": "双非进大厂需要多段大厂实习",
        "claim_type": "practitioner_experience",
        "source": {"type": "practitioner", "name": "阿里 HR"},
    })
    assert out["isError"] is True
    assert "scope" in out["message"]

    out = _record({
        "statement": "双非进大厂需要多段大厂实习",
        "claim_type": "practitioner_experience",
        "source": {"type": "practitioner"},
        "scope": {"education": "双非本"},
    })
    assert out["isError"] is True
    assert "source.name" in out["message"]


def test_record_and_list_claims(temp_profile):
    from src.server import list_claims

    first = _record({
        "statement": "双非进大厂常见多段大厂实习，每段约 6 个月",
        "claim_type": "practitioner_experience",
        "source": {"type": "practitioner", "name": "阿里 HR", "date": "2026-11-11"},
        "scope": {"education": "双非本", "channel": "校招"},
        "confidence": "medium",
        "limitation": "单一口述，未做统计",
        "expires_at": "2027-11-11",
    })
    assert not first.get("isError"), first
    assert first["claim"]["id"] == "cl_001"

    second = _record({
        "statement": "某 JD 要求本科及以上",
        "claim_type": "fact",
        "source": {"type": "jd", "name": "某公司校招 JD", "url": "https://example.com/jd/1"},
        "scope": {"role": "后端"},
    })
    assert second["claim"]["id"] == "cl_002"

    all_claims = json.loads(list_claims())
    assert all_claims["count"] == 2

    filtered = json.loads(list_claims("阿里"))
    assert filtered["count"] == 1
    assert filtered["items"][0]["source"]["name"] == "阿里 HR"

    profile = profile_module.load_profile()
    assert [claim.id for claim in profile.claims] == ["cl_001", "cl_002"]


def test_invalid_claim_type_and_expiry(temp_profile):
    out = _record({"statement": "x", "claim_type": "rumor"})
    assert out["isError"] is True

    out = _record({
        "statement": "x",
        "claim_type": "fact",
        "source": {"name": "某 JD"},
        "expires_at": "2026-13-40",
    })
    assert out["isError"] is True


def test_inference_can_be_recorded_without_source(temp_profile):
    out = _record({"statement": "可能需要两段实习", "claim_type": "inference"})
    assert not out.get("isError"), out
    assert out["claim"]["confidence"] == "low"
    assert any("推断" in note for note in out["notes"])
