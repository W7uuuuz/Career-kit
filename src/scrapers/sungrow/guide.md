# 阳光电源社会招聘

## 用途

阳光电源社会招聘 JD。数据来自 `app.mokahr.com` 的 Moka 招聘门户，
覆盖电力电子、硬件、软件、算法、储能、风能、氢能等方向。
接口响应为 AES 加密，scraper 在本地解密后返回结构化字段。

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `keyword` | 否 | 搜索关键词，如 `"硬件"`、`"算法"`、`"储能"`，服务端过滤 |
| `city` | 否 | 城市名，如 `"合肥"`、`"深圳"`，本地过滤 |
| `limit` | 否 | 返回数量上限，默认 20，最大 100 |

## 调用示例

```python
fetch_company_jobs(company="sungrow", params='{"keyword":"硬件","city":"合肥","limit":10}')
```

返回结果中的 `url` 形如：

```text
https://app.mokahr.com/social-recruitment/sungrow/94415#/job/<jobId>
```

可直接传给 `fetch_jd_detail`。

## 返回字段

列表：`title`、`url`、`company`、`location`、`department`、`summary`、
`job_id`、`source`。

详情：`title`、`company`、`location`、`department`、`salary`、
`description`、`requirements`、`job_type`、`source`。

## 注意事项

- 不公开薪资，`salary` 通常为空。
- 列表接口的关键词为服务端过滤，城市为本地过滤。
- 详情页为 SPA，scraper 直接调用 Moka 详情接口并解密，无需浏览器。
- 解密依赖 `cryptography`（已在项目依赖中声明）。
