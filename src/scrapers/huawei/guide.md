# 华为社会招聘

## 用途

华为社会招聘 JD。数据来自 `career.huawei.com` 的公开接口，
列表响应已包含岗位职责（标准职责）与任职要求（语言/教育/技能/知识），
适合做研发、算法、架构、财经、法务等方向的岗位分析。

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `keyword` | 否 | 搜索关键词，如 `"AI"`、`"算法"`、`"架构"`，对岗位名称/JD/部门做本地过滤 |
| `city` | 否 | 城市名，如 `"深圳"`、`"北京"`、`"上海"`，本地过滤 |
| `limit` | 否 | 返回数量上限，默认 20，最大 100 |

## 调用示例

```python
fetch_company_jobs(company="huawei", params='{"keyword":"AI","city":"深圳","limit":10}')
```

返回结果中的 `url` 形如：

```text
https://career.huawei.com/cn/social-recruitment-job-list?jobId=<jobId>
```

可直接传给 `fetch_jd_detail`，详情来自搜索时的列表快照。

## 返回字段

列表：`title`、`url`、`company`、`location`、`department`、`summary`、
`description`、`requirements`、`job_id`、`job_family`、`experience`、
`education`、`publish_date`、`source`。

详情：`title`、`company`、`location`、`department`、`salary`、
`description`、`requirements`、`job_family`、`experience`、`source`。

## 注意事项

- 不公开薪资，`salary` 通常为空。
- 接口需要固定租户头（`x-jalor-tenantalias: hcm` 等），scraper 已内置。
- 关键词与城市为本地过滤；scraper 会翻页直到满足 `limit`。
- 详情页依赖搜索快照；未先搜索直接调用详情会返回提示。
