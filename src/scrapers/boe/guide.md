# 京东方社会招聘

## 用途

京东方（BOE）社会招聘 JD。数据来自 `boe.zhiye.com` 的北森公开接口，
列表响应已包含岗位职责与任职要求，适合做岗位要求分析和差距对比。

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `keyword` | 否 | 搜索关键词，如 `"算法"`、`"工艺"`、`"Java"` |
| `city` | 否 | 城市名，如 `"北京"`、`"合肥"`，本地过滤 |
| `limit` | 否 | 返回数量上限，默认 20，最大 100 |

## 调用示例

```python
fetch_company_jobs(company="boe", params='{"keyword":"算法","city":"北京","limit":10}')
```

返回结果中的 `url` 形如：

```text
https://boe.zhiye.com/social/jobs?jobAdId=<jobAdId>
```

可直接传给 `fetch_jd_detail`，详情来自搜索时的列表快照。

## 返回字段

列表：`title`、`url`、`company`、`location`、`department`、`summary`、
`description`、`requirements`、`job_id`、`salary`、`source`。

详情：`title`、`company`、`location`、`department`、`salary`、
`description`、`requirements`、`source`。

## 注意事项

- 不公开薪资，`salary` 通常为空。
- 列表接口一次返回 30 条，scraper 会翻页直到满足 `limit`。
- 详情页依赖搜索快照；未先搜索直接调用详情会返回提示。
