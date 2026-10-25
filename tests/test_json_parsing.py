"""工具层 JSON 解析回归：多策略解析（原文 → 围栏 → 平衡对象提取）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

import src.tools.profile as profile_module
from src.tools.errors import InvalidJsonError
from src.tools.tool_helpers import _json_candidates, _parse_json_param


@pytest.fixture()
def temp_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(profile_module, "PROFILE_DIR", tmp_path)
    return tmp_path


# === 纯解析策略 ===


def test_direct_json_object():
    assert _parse_json_param('{"a": 1}') == {"a": 1}


def test_fenced_json_block():
    raw = "说明文字\n```json\n{\"match_score\": 65, \"skill_gaps\": []}\n```\n尾注"
    assert _parse_json_param(raw) == {"match_score": 65, "skill_gaps": []}


def test_prose_wrapped_object():
    raw = '好的，以下是分析结果：{"match_score": 50, "note": "结论"} 如需调整请告知。'
    assert _parse_json_param(raw)["match_score"] == 50


def test_dotted_braces_junk_then_real_object():
    """散文里的 {x} 假象不应挡住后面的真实对象（候选连续扫描）。"""
    raw = "| a | {x} |\n|---|---|\n| {y: 1} | z |\n\n{\"ok\": 6}"
    assert _parse_json_param(raw)["ok"] == 6


def test_junk_object_does_not_shadow_real_nested_object():
    """{x} 在前、含嵌套完整对象在后：仍应解析出后者。"""
    raw = '先看这个 {x}，再看 {"a": {"b": "c}d"}, "n": 9}'
    data = _parse_json_param(raw)
    assert data["n"] == 9 and data["a"] == {"b": "c}d"}


def test_empty_braces_do_not_shadow_later_object():
    """`{}` 能空 parse，但应优先取后面的真实对象。"""
    raw = "{} }}} {\"n\": 8}"
    assert _parse_json_param(raw)["n"] == 8


def test_empty_brace_fall_back():
    """全链只有空对象可 parse 时，返回它而不是报错。"""
    assert _parse_json_param("前后解释 {} 后记") == {}


def test_braces_inside_strings_do_not_confuse_scanner():
    raw = '前言 {"text": "包含 { 与 } 的字符串", "n": 1} 后记'
    assert _parse_json_param(raw)["n"] == 1


def test_nested_objects_balanced_scan():
    raw = '结果：{"gap": {"skill": "RAG"}, "arr": [{"x": 1}]} done'
    assert _parse_json_param(raw)["gap"] == {"skill": "RAG"}


def test_escaped_quote_inside_string():
    raw = r'a {"s": "quote \" brace } inside", "n": 2}'
    assert _parse_json_param(raw)["n"] == 2


def test_non_object_rejected():
    with pytest.raises(InvalidJsonError) as exc_info:
        _parse_json_param("[1, 2, 3]")
    assert "JSON 对象" in exc_info.value.message


def test_empty_rejected():
    with pytest.raises(InvalidJsonError):
        _parse_json_param("   ")


def test_garbage_rejected_with_hint():
    with pytest.raises(InvalidJsonError) as exc_info:
        _parse_json_param("完全不是 JSON 的输出")
    assert "重试" in exc_info.value.message or "只返回" in exc_info.value.message


def test_candidates_order_prefers_raw_then_fence_then_scan():
    raw = '```json\n{"a": 1}\n```'
    cands = _json_candidates(raw)
    assert cands[0] == raw          # 原文优先（原文非 dict 时才会继续）
    assert any(c == '{"a": 1}' for c in cands[1:])


# === 工具级回归：核心保存链路接受围栏 JSON ===


def test_save_gap_analysis_accepts_fenced_json(temp_profile):
    from src.server import save_gap_analysis

    raw = (
        "以下是差距分析：\n```json\n"
        + json.dumps({
            "match_score": 60,
            "skill_gaps": [{"skill": "RAG", "current_level": "无",
                            "required_level": "熟练", "source": "BOSS JD"}],
        }, ensure_ascii=False)
        + "\n```"
    )
    result = json.loads(save_gap_analysis(gap_json=raw))
    assert not result.get("isError"), result
    assert profile_module.load_profile().gap["match_score"] == 60


def test_import_jd_accepts_fenced_json(temp_profile):
    from src.server import import_jd

    raw = '```json\n{"company": "字节", "role": "Agent 工程师", "requirements": ["RAG"]}\n```'
    result = import_jd(jd_text=raw)
    assert "已导入目标 JD" in result
    assert profile_module.load_profile().target_jd["company"] == "字节"


def test_import_jd_still_rejects_plain_text(temp_profile):
    from src.server import import_jd

    result = json.loads(import_jd(jd_text="这是纯文本 JD，不是 JSON"))
    assert result.get("isError") is True
    assert result["code"] == "INVALID_JSON"
    assert not profile_module.load_profile().target_jd


def test_save_roadmap_accepts_prose_wrapped_json(temp_profile):
    from src.server import save_roadmap

    roadmap = json.dumps({
        "strategy_summary": "s",
        "phases": [{"type": "learn", "name": "基础", "goal": "入门",
                    "kpi": {"metric": "刷题", "target": "50 题"},
                    "milestones": [{"name": "M1", "done_criteria": "能独立写出"}]}],
    }, ensure_ascii=False)
    raw = f"完整路线图如下：\n{roadmap}\n\n请确认后保存。"
    result = json.loads(save_roadmap(roadmap_json=raw))
    assert not result.get("isError"), result
    profile = profile_module.load_profile()
    assert profile.plan["roadmap"]["phases"][0]["name"] == "基础"


def test_apply_insight_accepts_fenced_json(temp_profile):
    from src.server import apply_insight

    raw = '```json\n{"trigger_type": "event", "status": "on_track", ' \
          '"summary": "s", "insights": [], "adjustment_needed": false, "user_message": "m"}\n```'
    result = json.loads(apply_insight(insight_json=raw))
    assert not result.get("isError"), result


def test_parse_roadmap_degrades_to_raw_on_garbage():
    from src.tools.roadmap import parse_roadmap

    out = parse_roadmap("彻底不是 JSON")
    assert out["roadmap"]["phases"] == []
    assert "彻底不是 JSON" in out["raw_roadmap"]


def test_parse_roadmap_accepts_prose_wrapped():
    from src.tools.roadmap import parse_roadmap

    out = parse_roadmap('开头 {"roadmap": {"phases": [{"name": "基础"}]}} 结尾')
    assert out["roadmap"]["phases"][0]["name"] == "基础"
