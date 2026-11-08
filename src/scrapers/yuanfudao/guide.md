# 猿辅导校园招聘

## 用途

猿辅导校园招聘 JD。数据来自 `hr.yuanfudao.com` 的 Moka 招聘门户（粉笔站点），
面向校招岗位，覆盖教研、算法、研发、产品等方向。
接口响应为 AES 加密，scraper 在本地解密后返回结构化字段。

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `keyword` | 否 | 搜索关键词，如 `"算法"`、`"教研"`，服务端过滤 |
| `city` | 否 | 城市名，如 `"北京"`，本地过滤 |
| `limit` | 否 | 返回数量上限，默认 20，最大 100 |

## 调用示例

```python
fetch_company_jobs(company="yuanfudao", params='{"keyword":"算法","city":"北京","limit":10}')
```

返回结果中的 `url` 形如：

```text
https://hr.yuanfudao.com/campus-recruitment/fenbi/47742#/job/<jobId>
```

可直接传给 `fetch_jd_detail`。

## 返回字段

列表：`title`、`url`、`company`、`location`、`department`、`summary`、
`job_id`、`source`。

详情：`title`、`company`、`location`、`department`、`salary`、
`description`、`requirements`、`job_type`、`source`。

## 注意事项

- 本源为猿辅导校招 Moka 门户，不公开薪资，`salary` 通常为空。
- 关键词为服务端过滤，城市为本地过滤。
- 详情页为 SPA，scraper 直接调用 Moka 详情接口并解密，无需浏览器；
  也可先 `search` 拿到 `url` 再 `get_detail`，或直接用列表返回的 url 取详情。
- 站点路径为 `/campus-recruitment/` 校招门户，Moka 组织 ID 为 `fenbi`。
