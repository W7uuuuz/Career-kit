"""资格谓词：用户可投边界 × 岗位硬信号。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.domain.eligibility import (
    EligibilityPolicy,
    evaluate,
    extract_signals,
    infer_job_kind,
)


def _policy(**overrides) -> EligibilityPolicy:
    base = EligibilityPolicy(
        role="AI Agent 开发",
        direction_terms=["agent", "ai"],
        city="上海",
        job_kind="intern",
        graduation_year=2028,
        degree="本科",
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def test_graduation_mismatch_drops_unopened_cohort():
    signals = extract_signals(
        "AI Agent 开发实习生",
        "面向 2027 届毕业生（2026.9-2027.8 毕业），本科及以上，上海",
        "上海",
    )
    verdict = evaluate(_policy(), signals)
    assert verdict.status == "ineligible"
    assert "graduation_mismatch" in verdict.reasons


def test_no_graduation_signal_is_open_to_user():
    signals = extract_signals(
        "AI Agent 开发实习生", "日常实习，本科及以上，上海", "上海"
    )
    verdict = evaluate(_policy(), signals)
    assert verdict.status == "eligible"
    assert verdict.reasons == []


def test_recruit_type_mismatch():
    signals = extract_signals("AI Agent 开发（社招）", "社会招聘，上海", "上海")
    verdict = evaluate(_policy(), signals)
    assert "recruit_type_mismatch" in verdict.reasons


def test_exclude_direction_wins():
    signals = extract_signals(
        "大模型算法工程师", "负责算法研究与模型训练，上海", "上海"
    )
    verdict = evaluate(_policy(exclude_directions=["算法"]), signals)
    assert "direction_excluded" in verdict.reasons


def test_degree_insufficient():
    signals = extract_signals(
        "AI Agent 开发实习生", "硕士及以上，上海", "上海"
    )
    verdict = evaluate(_policy(degree="本科"), signals)
    assert "degree_insufficient" in verdict.reasons


def test_city_mismatch_and_remote_exception():
    mismatch = extract_signals("AI Agent 实习生", "本科及以上", "北京")
    assert "city_mismatch" in evaluate(_policy(), mismatch).reasons
    remote = extract_signals("AI Agent 实习生", "本科及以上", "远程")
    assert "city_mismatch" not in evaluate(_policy(), remote).reasons


def test_direction_mismatch_and_unknown_text():
    mismatch = extract_signals("客服质管专员", "负责客服质检", "上海")
    assert "direction_mismatch" in evaluate(_policy(), mismatch).reasons

    unknown = extract_signals("AI Agent 开发实习生", "", "")
    verdict = evaluate(_policy(), unknown)
    assert verdict.status == "unknown"
    assert any("未确认" in note for note in verdict.notes)


def test_infer_job_kind_does_not_guess_when_unclear():
    assert infer_job_kind("AI Agent 开发") == ""
    assert infer_job_kind("AI Agent 日常实习") == "intern"
    assert infer_job_kind("2027 届校园招聘") == "campus"
    assert infer_job_kind("社会招聘") == "social"
