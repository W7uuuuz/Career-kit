# 行业去向数据接入

行业快照的“同行业/相关专业去向”来自可选的数据文件；未接入时快照会如实显示缺口，不会用 LLM 记忆补数字。

## 文件位置

```text
~/.career-kit/industry_outcomes/<industry_id>.json
```

MVP 的 `industry_id` 为 `internet`（互联网/软件）、`energy`（能源动力）。

## 最小结构

```json
{
  "industry_id": "internet",
  "generated_at": "2026-10-27",
  "samples": [
    {
      "school": "某大学",
      "major": "计算机科学与技术",
      "degree": "本科",
      "graduation_year": "2025",
      "sample_size": 186,
      "destinations": {
        "升学": 60,
        "就业": 95,
        "灵活就业": 15,
        "待就业": 16
      },
      "industries": [
        {"name": "互联网/软件", "count": 52},
        {"name": "制造业", "count": 18}
      ],
      "cities": [
        {"name": "杭州", "count": 31},
        {"name": "上海", "count": 22}
      ],
      "salary": {
        "count": 80,
        "median": 7200,
        "p25": 6000,
        "p75": 9000,
        "period": "月",
        "note": "毕业半年后月收入"
      },
      "source_url": "https://example.edu/employment-report.pdf",
      "source_title": "某大学 2025 届毕业生就业质量报告"
    }
  ]
}
```

## 规则

- 只放公开、可追溯的聚合数据；不要放个人级信息。
- `sample_size` 是分母；去向计数之和应接近样本数，无法对齐时在 `note` 说明。
- 薪资必须写口径：毕业半年后 / 招聘区间 / 月薪 / 年薪。
- 每个样本带 `source_url`；没有来源的数据不要接入。
- 小样本（如 n<20）应在展示时标注“样本不足”。

## 与招聘数据的关系

- 去向数据回答“同行业/相关专业毕业去哪”。
- BOSS 招聘数据回答“现在市场在招什么、给多少”。
- 两者不能混成一个数字；快照会分开返回。
