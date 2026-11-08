# 芒果TV社会招聘

## 用途

芒果TV社会招聘 JD。数据来自 `hr.mgtv.com` 的 Moka 招聘门户，
覆盖内容制作、技术研发、运营、市场等方向。
接口响应为 AES 加密，scraper 在本地解密后返回结构化字段。

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `keyword` | 否 | 搜索关键词，如 `"运营"`、`"后端"`，服务端过滤 |
| `city` | 否 | 城市名，如 `"长沙"`，本地过滤 |
| `limit` | 否 | 返回数量上限，默认 20，最大 100 |

## 调用示例

```python
fetch_company_jobs(company="mgtv", params='{"keyword":"后端","city":"长沙","limit":10}')
```

返回结果中的 `url` 形如：

```text
https://hr.mgtv.com/social-recruitment/mgtv/44505#/job/<jobId>
```

可直接传给 `fetch_jd_detail`。

## 返回字段

列表：`title`、`url`、`company`、`location`、`department`、`summary`、
`job_id`、`source`。

详情：`title`、`company`、`location`、`department`、`salary`、
`description`、`requirements`、`job_type`、`source`。

## 注意事项

- 本源为芒果TV社招 Moka 门户，不公开薪资，`salary` 通常为空。
- 关键词为服务端过滤，城市为本地过滤。
- 详情页为 SPA，scraper 直接调用 Moka 详情接口并解密，无需浏览器；
  也可先 `search` 拿到 `url` 再 `get_detail`，或直接用列表返回的 url 取详情。
- 该门户使用独立域名 `hr.mgtv.com`。
