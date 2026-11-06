# 中国中车社会招聘

## 用途

中国中车社会招聘 JD。数据来自 `crrc.hotjob.cn` 的大易公开接口，
支持列表与详情，覆盖机械、电气、电子信息、材料等岗位族。

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `keyword` | 否 | 搜索关键词，如 `"电气"`、`"无人机"`、`"算法"`，本地过滤岗位名称/类别/公司 |
| `city` | 否 | 城市名，如 `"北京"`、`"南京"`，本地过滤工作地点 |
| `limit` | 否 | 返回数量上限，默认 20，最大 100 |

## 调用示例

```python
fetch_company_jobs(company="crrc", params='{"keyword":"电气","city":"北京","limit":10}')
```

返回结果中的 `url` 形如：

```text
https://crrc.hotjob.cn/SU64d47c466202cc36e27a52d4/pb/posDetail.html?postId=<postId>&postType=<postType>
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
