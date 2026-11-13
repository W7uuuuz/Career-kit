"""草稿分片与截断识别。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.tools import draft_store, profile as profile_store
from src.tools.errors import ParamTruncatedError
from src.tools.tool_helpers import _parse_json_param


@pytest.fixture()
def local_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(profile_store, "PROFILE_DIR", tmp_path / "data")
    return tmp_path


def test_draft_chunks_join_and_clear(local_profile):
    created = draft_store.create("gap")
    draft_id = created["draft_id"]
    draft_store.append(draft_id, '{"match_score": 60, ')
    draft_store.append(draft_id, '"strengths": []}')
    assert draft_store.read_text(draft_id) == '{"match_score": 60, "strengths": []}'
    assert draft_store.status(draft_id)["complete_hint"] == "balanced_or_non_json"
    draft_store.clear(draft_id)
    with pytest.raises(draft_store.DraftError):
        draft_store.status(draft_id)


def test_truncated_param_has_clear_code():
    truncated = '{"match_score": 60, "strengths": [{"area": "前端' + "填充" * 800
    with pytest.raises(ParamTruncatedError) as exc:
        _parse_json_param(truncated, "差距分析")
    assert exc.value.code == "PARAM_TRUNCATED"
    assert "截断" in exc.value.message
