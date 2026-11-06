# 特变电工社会招聘

## 用途

特变电工社会招聘 JD。数据来自 `wecruit.hotjob.cn` 的大易公开接口，
支持列表与详情，覆盖电气、机械、新能源、国际业务等岗位。

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `keyword` | 否 | 搜索关键词，如 `"电气"`、`"变压器"`、`"算法"`，本地过滤 |
| `city` | 否 | 城市名，如 `"乌鲁木齐"`、`"北京"`，本地过滤 |
| `limit` | 否 | 返回数量上限，默认 20，最大 100 |

## 调用示例

```python
fetch_company_jobs(company="tebian", params='{"keyword":"电气","city":"乌鲁木齐","limit":10}')
```

返回结果中的 `url` 形如：

```text
https://wecruit.hotjob.cn/SU612f55eebef57c0616450aa2/pb/posDetail.html?postId=<postId>&postType=<postType>
```

可直接传给 `fetch_jd_detail`。

## 返回字段

列表：`title`、`url`、`company`、`location`、`department`、`summary`、
`job_id`、`job_type`、`education`、`publish_date`、`source`。

详情：`title`、`company`、`location`、`department`、`salary`、
`description`、`requirements`、`education`、`job_type`、`publish_date`、`source`。

## 注意事项

- 不公开薪资，`salary` 通常为空。
- 关键词与城市为本地过滤；scraper 会翻页直到满足 `limit`。
- 详情接口按 `postId` 查询，URL 中必须保留 `postId`。
