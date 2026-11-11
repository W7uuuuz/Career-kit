"""案例与 JD 口径分离回归——本地 JD 不得被算作面经案例。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding="utf-8")


def _write_local_jd(tmp_path: Path, monkeypatch) -> dict:
    import src.case_search as cs

    knowledge = tmp_path / "knowledge"
    jd_dir = knowledge / "jds" / "bytedance"
    jd_dir.mkdir(parents=True)
    payload = {
        "title": "AI Agent 开发工程师",
        "company": "字节跳动",
        "location": "上海",
        "description": "负责 Agent 平台与评测体系",
        "requirements": "熟悉 Python / RAG",
        "source": "bytedance",
        "url": "https://jobs.bytedance.com/campus/position/1/detail",
    }
    path = jd_dir / "agent.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(cs, "KNOWLEDGE_DIR", knowledge)
    return {"source": "jds/bytedance/agent.json", "content": json.dumps(payload, ensure_ascii=False)}


def test_local_jd_is_jd_category_with_local_source(tmp_path, monkeypatch):
    """B5/B6：本地 JD 判为企业要求（jd），来源标签为 local，不退化成 bytedance。"""
    import src.case_search as cs

    row = _write_local_jd(tmp_path, monkeypatch)
    item = cs._local_row_to_item(row)

    assert item["origin"] == "local_jd"
    assert item["source"] == "local"

    card = cs._row_to_card(item)
    assert card is not None
    assert card["category"] == "jd"
    assert card["category_label"] == "企业要求"
    assert card["kind"] == "interview_requirements"


def test_render_cases_keeps_cases_and_jd_in_separate_sections():
    """B5：他人经验（面经/成功经验）与企业要求（JD）分组展示，不混列。"""
    import src.case_search as cs

    result = {
        "cases": [
            {
                "kind": "success_experience",
                "category": "case",
                "category_label": "他人经验",
                "title": "双非本 秋招上岸复盘",
                "source": "nowcoder",
                "url": "nc://1",
                "background": {},
                "highlights": [],
            },
            {
                "kind": "interview_requirements",
                "category": "case",
                "category_label": "他人经验",
                "title": "字节 Agent 一面面经",
                "source": "nowcoder",
                "url": "nc://2",
                "background": {},
                "highlights": [],
            },
            {
                "kind": "interview_requirements",
                "category": "jd",
                "category_label": "企业要求",
                "title": "AI Agent 开发工程师 JD",
                "source": "local",
                "origin": "local_jd",
                "url": "https://jobs.bytedance.com/1",
                "background": {"company": "字节跳动"},
                "highlights": [],
            },
        ],
        "warnings": [],
        "sources": {"nowcoder": 2, "local": 1},
    }

    text = cs.render_cases(result, "AI Agent 开发", "", "")
    case_part, jd_part = text.split("## 企业要求", 1)

    assert "双非本 秋招上岸复盘" in case_part
    assert "字节 Agent 一面面经" in case_part
    assert "他人经验" in case_part
    assert "AI Agent 开发工程师 JD" not in case_part
    assert "AI Agent 开发工程师 JD" in jd_part
    assert "企业要求" in jd_part
