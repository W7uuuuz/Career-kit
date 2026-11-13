"""岗位资格谓词：用户可投边界 × 岗位硬信号。

第一性原理：系统不需要判断「某届是否开放」，只需要回答两个确定问题——
用户要投哪类岗位（job_kind），以及这一条岗位接不接受他（evaluate）。
不合格的岗位不进样本、不进统计、不展示；缺信号的岗位保留但标注。

纯函数模块：不依赖存储、抓取与报告，便于单测与复用。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Any, Literal

JobKind = Literal["intern", "campus", "social"]
VerdictStatus = Literal["eligible", "ineligible", "unknown"]
ScreenReason = Literal[
    "recruit_type_mismatch",
    "graduation_mismatch",
    "degree_insufficient",
    "city_mismatch",
    "direction_excluded",
    "direction_mismatch",
]

JOB_KINDS: tuple[str, ...] = ("intern", "campus", "social")
_DEGREE_RANK = {"专科": 0, "大专": 0, "本科": 1, "硕士": 2, "研究生": 2, "博士": 3}
_GENERIC_TERMS = frozenset(
    {
        "开发", "工程师", "研发", "经理", "专员", "主管", "总监", "助理",
        "实习", "日常", "岗位", "职位", "方向", "工作", "全职", "兼职",
        "校招", "社招", "应届", "招聘",
    }
)
_TOKEN_SPLIT_RE = re.compile(r"[\s,，、;；/|()（）\-—_·]+")
_ASCII_TOKEN_RE = re.compile(r"[a-z][a-z0-9+#.]*")
_CJK_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]{2,}")
_REMOTE_HINTS = ("远程", "全国", "不限", "remote", "anywhere")
_AI_SIGNALS = (
    "ai", "agent", "llm", "大模型", "模型", "算法", "机器学习", "深度学习",
    "nlp", "rag", "langchain", "langgraph", "智能",
)
_AI_FAMILY_TERMS = (
    "ai", "agent", "llm", "大模型", "机器学习", "深度学习",
    "nlp", "rag", "langchain", "langgraph", "prompt",
)

_GRAD_RANGE_RE = re.compile(
    r"(20\d{2})\s*[.\-/年]\s*\d{1,2}\s*月?\s*[-~至到]\s*(20\d{2})\s*[.\-/年]\s*\d{1,2}\s*月?"
)
_GRAD_YEAR_RE = re.compile(r"(20\d{2})\s*届")
_GRAD_SHORT_RE = re.compile(r"(?<!\d)(\d{2})\s*届")
_GRAD_GRADUATE_RE = re.compile(r"(20\d{2})\s*年\s*(?:毕业|应届)")
_DEGREE_MIN_RE = re.compile(
    r"(博士|硕士|研究生|本科|专科|大专)(?:学历|学位)?\s*(?:及以上|以上|起)"
)
_RECRUIT_INTERN = ("实习", "intern", "日常实习")
_RECRUIT_CAMPUS = ("校招", "校园招聘", "应届", "campus", "graduate")
_RECRUIT_SOCIAL = ("社招", "社会招聘", "experienced", "social")


@dataclass
class EligibilityPolicy:
    """用户侧的可投边界；从档案派生，允许用户确认或覆盖。"""

    role: str = ""
    direction_terms: list[str] = field(default_factory=list)
    city: str = ""
    job_kind: str = "intern"
    graduation_year: int | None = None
    degree: str = ""
    exclude_directions: list[str] = field(default_factory=list)
    min_direction_score: int = 1

    @classmethod
    def from_profile(cls, profile: Any) -> EligibilityPolicy:
        who = _as_dict(getattr(profile, "who", None))
        want = _as_dict(getattr(profile, "want", None))
        role = _first_text(
            want.get("target_role"), want.get("role"), want.get("direction")
        )
        direction = _first_text(want.get("direction"), role)
        city = _first_text(want.get("city"), who.get("city"))
        job_kind = normalize_job_kind(
            want.get("job_kind") or want.get("recruit_type") or ""
        ) or infer_job_kind(f"{role} {direction}")
        graduation = _first_text(
            who.get("graduation_year"), want.get("graduation_year")
        )
        degree = _degree_of(
            _first_text(who.get("degree"), who.get("education"), want.get("degree"))
        )
        terms = sorted(
            {
                *_expanded_terms(role),
                *_expanded_terms(direction),
            }
        )
        return cls(
            role=role,
            direction_terms=terms,
            city=city,
            job_kind=job_kind,
            graduation_year=_year_of(graduation),
            degree=degree,
            exclude_directions=_as_list(want.get("exclude_directions")),
        )

    def with_context(
        self, *, role: str = "", direction: str = "", city: str = ""
    ) -> EligibilityPolicy:
        """用本轮调研参数补全档案缺失项（不改档案本身）。"""
        clone = replace(self)
        clone.role = _first_text(role, direction, self.role)
        clone.city = _first_text(city, self.city)
        clone.direction_terms = sorted(
            {
                *self.direction_terms,
                *_expanded_terms(role),
                *_expanded_terms(direction),
            }
        )
        if not clone.job_kind:
            clone.job_kind = infer_job_kind(f"{role} {direction}")
        return clone

    @classmethod
    def from_target(cls, target: Any, profile: Any) -> EligibilityPolicy:
        """档案优先、TargetSpec 覆盖身份字段。"""
        policy = cls.from_profile(profile)
        role = _first_text(getattr(target, "role", ""), policy.role)
        direction = _first_text(getattr(target, "direction", ""), role)
        policy.role = role
        policy.city = _first_text(getattr(target, "city", ""), policy.city)
        policy.job_kind = normalize_job_kind(
            getattr(target, "job_kind", "")
        ) or policy.job_kind
        policy.graduation_year = (
            _year_of(getattr(target, "graduation_year", "")) or policy.graduation_year
        )
        policy.direction_terms = sorted(
            {
                *policy.direction_terms,
                *_expanded_terms(role),
                *_expanded_terms(direction),
            }
        )
        return policy


@dataclass
class PostingSignals:
    """岗位侧可确定性抽取的硬信号；抽不到留空，不猜测。"""

    title: str = ""
    text: str = ""
    location: str = ""
    recruit_type: str = "unknown"
    graduation_years: list[int] = field(default_factory=list)
    degree_min: str = ""


@dataclass
class Verdict:
    status: str
    reasons: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    direction_score: int = 0

    @property
    def eligible(self) -> bool:
        return self.status != "ineligible"


def normalize_job_kind(value: Any) -> str:
    text = str(value or "").strip().lower()
    mapping = {
        "intern": "intern",
        "internship": "intern",
        "实习": "intern",
        "日常实习": "intern",
        "campus": "campus",
        "校招": "campus",
        "校园招聘": "campus",
        "应届": "campus",
        "social": "social",
        "社招": "social",
        "社会招聘": "social",
    }
    return mapping.get(text, "")


def infer_job_kind(text: str) -> str:
    low = str(text or "").lower()
    if any(token in low for token in _RECRUIT_INTERN):
        return "intern"
    if any(token in low for token in _RECRUIT_CAMPUS):
        return "campus"
    if any(token in low for token in _RECRUIT_SOCIAL):
        return "social"
    return ""


def extract_signals(
    title: Any,
    text: Any = "",
    location: Any = "",
) -> PostingSignals:
    title_text = str(title or "")
    body = " ".join(str(text or "").split())
    merged = f"{title_text} {body}".strip()
    return PostingSignals(
        title=title_text,
        text=merged,
        location=str(location or "").strip(),
        recruit_type=_extract_recruit_type(title_text, body),
        graduation_years=_extract_graduation_years(merged),
        degree_min=_extract_degree_min(merged),
    )


def evaluate(policy: EligibilityPolicy, signals: PostingSignals) -> Verdict:
    """唯一资格判定：任何 ineligible 原因 → 丢弃；无原因但有缺口 → unknown。"""
    reasons: list[str] = []
    notes: list[str] = []

    if (
        policy.job_kind
        and signals.recruit_type != "unknown"
        and signals.recruit_type != policy.job_kind
    ):
        reasons.append("recruit_type_mismatch")

    if (
        policy.graduation_year
        and signals.graduation_years
        and int(policy.graduation_year) not in signals.graduation_years
    ):
        reasons.append("graduation_mismatch")

    if (
        policy.degree
        and signals.degree_min
        and _degree_rank(policy.degree) < _degree_rank(signals.degree_min)
    ):
        reasons.append("degree_insufficient")

    if policy.city and signals.location and not _city_ok(policy.city, signals.location):
        reasons.append("city_mismatch")

    excluded = [term for term in policy.exclude_directions if _term_in(term, signals.text)]
    if excluded:
        reasons.append("direction_excluded")
        notes.append("命中排除方向：" + "、".join(excluded))

    score = direction_score(policy, signals.text)
    if (
        not reasons
        and policy.direction_terms
        and signals.text.strip()
        and score < policy.min_direction_score
    ):
        reasons.append("direction_mismatch")

    if signals.text.strip() == "":
        notes.append("岗位正文缺失，方向与资格未确认")
    if policy.city and not signals.location:
        notes.append("岗位地点缺失，城市资格未确认")

    if reasons:
        status = "ineligible"
    elif any("未确认" in note for note in notes):
        status = "unknown"
    else:
        status = "eligible"

    return Verdict(
        status=status,
        reasons=list(dict.fromkeys(reasons)),
        notes=notes,
        direction_score=score,
    )


def direction_score(policy: EligibilityPolicy, text: Any) -> int:
    """方向相关度 0-100；标题命中权重更高，只做字面匹配。"""
    haystack = str(text or "").lower()
    terms = [term for term in policy.direction_terms if term]
    if not terms or not haystack:
        return 0
    hits = [term for term in terms if _term_in(term, haystack)]
    if not hits:
        return 0
    ratio = len(hits) / len(terms)
    return min(100, int(round(40 + ratio * 60)))


def _extract_recruit_type(title: str, body: str) -> str:
    for text in (title, body):
        low = text.lower()
        if any(token in low for token in _RECRUIT_INTERN):
            return "intern"
        if any(token in low for token in _RECRUIT_CAMPUS):
            return "campus"
        if any(token in low for token in _RECRUIT_SOCIAL):
            return "social"
    return "unknown"


def _extract_graduation_years(text: str) -> list[int]:
    years: set[int] = set()
    for match in _GRAD_RANGE_RE.finditer(text):
        start, end = int(match.group(1)), int(match.group(2))
        if 0 <= end - start <= 5:
            years.update(range(start, end + 1))
    for match in _GRAD_YEAR_RE.finditer(text):
        years.add(int(match.group(1)))
    for match in _GRAD_GRADUATE_RE.finditer(text):
        years.add(int(match.group(1)))
    for match in _GRAD_SHORT_RE.finditer(text):
        year = int(match.group(1))
        if 0 <= year <= 99:
            years.add(2000 + year)
    return sorted(year for year in years if 2000 <= year <= 2100)


def _extract_degree_min(text: str) -> str:
    match = _DEGREE_MIN_RE.search(text)
    if not match:
        return ""
    return _degree_of(match.group(1))


def _degree_of(text: Any) -> str:
    raw = str(text or "")
    for degree in ("博士", "硕士", "研究生", "本科", "专科", "大专"):
        if degree in raw:
            return degree
    return ""


def _degree_rank(degree: str) -> int:
    return _DEGREE_RANK.get(str(degree or ""), -1)


def _city_ok(city: str, location: str) -> bool:
    target = str(city or "").replace("市", "").strip()
    place = str(location or "").replace("市", "").strip()
    if not target or not place:
        return True
    if any(hint in place.lower() for hint in _REMOTE_HINTS):
        return True
    return target in place


def _term_in(term: Any, text: str) -> bool:
    value = str(term or "").strip().lower()
    if len(value) < 2 or not text:
        return False
    haystack = text.lower()
    if value.isascii():
        pattern = rf"(?<![a-z0-9]){re.escape(value)}(?![a-z0-9])"
        return re.search(pattern, haystack) is not None
    return value in haystack


def _expanded_terms(text: Any) -> list[str]:
    """方向词 + AI 岗位族扩展词（只做字面匹配，宁少不脏）。"""
    raw = str(text or "").strip().lower()
    terms = direction_terms(raw)
    if any(signal in raw for signal in _AI_SIGNALS):
        terms.extend(
            term for term in _AI_FAMILY_TERMS if term not in _GENERIC_TERMS
        )
    return sorted(dict.fromkeys(terms))


def direction_terms(text: Any) -> list[str]:
    raw = str(text or "").strip().lower()
    if not raw:
        return []
    parts = [part for part in _TOKEN_SPLIT_RE.split(raw) if part]
    parts.extend(match.group(0) for match in _ASCII_TOKEN_RE.finditer(raw))
    parts.extend(match.group(0) for match in _CJK_TOKEN_RE.finditer(raw))
    terms: list[str] = []
    for part in parts:
        value = part.strip().lower()
        if len(value) < 2 or value in _GENERIC_TERMS or value in terms:
            continue
        terms.append(value)
    return terms


def _year_of(value: Any) -> int | None:
    match = re.search(r"(20\d{2}|\d{2})", str(value or ""))
    if not match:
        return None
    year = int(match.group(1))
    if year < 100:
        year += 2000
    return year if 2000 <= year <= 2100 else None


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    if not text:
        return []
    return [item for item in re.split(r"[,，、;；\s]+", text) if item]




