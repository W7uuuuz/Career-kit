# 哈啰社会招聘

## 用途

哈啰社会招聘 JD。数据来自 `hellobike.zhiye.com` 的北森公开接口，
列表响应已包含岗位职责与任职要求，适合做岗位要求分析和差距对比。

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `keyword` | 否 | 搜索关键词，如 `"Java"`、`"算法"`、`"运营"` |
| `city` | 否 | 城市名，如 `"上海"`、`"杭州"`，本地过滤 |
| `limit` | 否 | 返回数量上限，默认 20，最大 100 |

## 调用示例

```python
fetch_company_jobs(company="hello", params='{"keyword":"Java","city":"上海","limit":10}')
```

返回结果中的 `url` 形如：

```text
https://hellobike.zhiye.com/social/jobs?jobAdId=<jobAdId>
```

可直接传给 `fetch_jd_detail`，详情来自搜索时的列表快照。

## 返回字段

列表：`title`、`url`、`company`、`location`、`department`、`summary`、
`description`、`requirements`、`job_id`、`salary`、`source`。

详情：`title`、`company`、`location`、`department`、`salary`、
`description`、`requirements`、`source`。

## 注意事项

- 使用北森社招接口 `POST https://hellobike.zhiye.com/api/Jobad/GetJobAdPageList`。
- 列表响应已包含完整 JD（岗位职责与任职要求），无需再请求详情接口。
- 不公开具体薪资，`salary` 多为「面议」或为空。
- `keyword` 由服务端过滤，`city` 为结果本地过滤。
- 列表接口一次返回 30 条，scraper 会翻页直到满足 `limit`。
- 详情页依赖搜索快照；未先搜索直接调用详情会返回提示。
