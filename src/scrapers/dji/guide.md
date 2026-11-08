# 大疆社会招聘

## 用途

大疆社会招聘 JD。数据来自 `apply.careers.dji.com` 的 Moka 招聘门户，
覆盖研发、算法、硬件、供应链、市场等方向。
接口响应为 AES 加密，scraper 在本地解密后返回结构化字段。

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `keyword` | 否 | 搜索关键词，如 `"算法"`、`"硬件"`，服务端过滤 |
| `city` | 否 | 城市名，如 `"深圳"`，本地过滤 |
| `limit` | 否 | 返回数量上限，默认 20，最大 100 |

## 调用示例

```python
fetch_company_jobs(company="dji", params='{"keyword":"算法","city":"深圳","limit":10}')
```

返回结果中的 `url` 形如：

```text
https://apply.careers.dji.com/social-recruitment/dji/170070#/job/<jobId>
```

可直接传给 `fetch_jd_detail`。

## 返回字段

列表：`title`、`url`、`company`、`location`、`department`、`summary`、
`job_id`、`source`。

详情：`title`、`company`、`location`、`department`、`salary`、
`description`、`requirements`、`job_type`、`source`。

## 注意事项

- 本源为大疆社招 Moka 门户，不公开薪资，`salary` 通常为空。
- 关键词为服务端过滤，城市为本地过滤。
- 详情页为 SPA，scraper 直接调用 Moka 详情接口并解密，无需浏览器；
  也可先 `search` 拿到 `url` 再 `get_detail`，或直接用列表返回的 url 取详情。
- 该门户使用独立域名 `apply.careers.dji.com`，不走 `app.mokahr.com` 页面加载。
