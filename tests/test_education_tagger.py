"""学历标签归一（五档四层）回归测试——贴真实文本里常见的写法。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.education import (
    canonical_education,
    education_match_beta,
    education_search_words,
    normalize_education_tag,
)


def test_extract_tag_from_real_titles():
    # 牛客/GitHub 帖子标题的真实写法
    assert normalize_education_tag("27届双非本 offre 字节后端")["tag"] == "双非本"
    assert normalize_education_tag("211硕士 秋招复盘 字节 Agent 实习转正")["tag"] == "211硕"
    assert normalize_education_tag("985本科 一路面经到 offer")["tag"] == "985本"
    assert normalize_education_tag("二本三本合并后的普本 找工作经历")["tag"] == "双非本"
    assert normalize_education_tag("大专生逆袭 网瘾少年考研上岸")["tag"] == "专科"
    assert normalize_education_tag("2026届博士 高校企业选择")["tag"] == "博士"
    # 届别单独抽
    assert normalize_education_tag("双非本 字节 offer 27届")["year"] == "27届"
    # 未识别
    info = normalize_education_tag("一起加油")
    assert info["tier"] == "" and info["degree"] == "" and info["explicit"] is False


def test_canonical_education_accepts_common_inputs():
    assert canonical_education("双非本")["tag"] == "双非本"
    assert canonical_education("211硕")["tag"] == "211硕"
    assert canonical_education("本科")["tier"] == "" and canonical_education("本科")["degree"] == "本科"
    assert canonical_education("二本")["tier"] == "双非"
    assert canonical_education("研究生")["degree"] == "硕士"
    # 无法归一要报错而非静默吞
    try:
        canonical_education("海龟毕业")
        raise AssertionError("应拒绝无法归一的 education")
    except ValueError:
        pass
    try:
        canonical_education("")
        raise AssertionError("空 education 应拒绝")
    except ValueError:
        pass


def test_match_beta_graded():
    cond = canonical_education("双非本")
    assert education_match_beta(cond, "27届双非本 字节后端 offer") == 3  # 全命中
    assert education_match_beta(cond, "双非硕 一面二面三面") == 2  # 档位同
    assert education_match_beta(cond, "211本科 面试") == 1  # 层级同
    assert education_match_beta(cond, "加油顺利") == 0  # 无线索

    cond2 = canonical_education("985")
    assert education_match_beta(cond2, "985校招 进行时") == 2  # 仅档位
    assert education_match_beta(cond2, "看了 3 场面经") == 0


def test_search_words_expand():
    words = education_search_words(canonical_education("双非本"))
    assert "双非" in words and "二本" in words and "本科" in words or "本" in words
    words2 = education_search_words(canonical_education("211硕"))
    assert "211" in words2 and ("硕士" in words2 or "研究生" in words2)
