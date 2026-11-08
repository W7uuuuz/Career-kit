# 盛趣游戏社会招聘

## 用途

盛趣游戏社会招聘 JD。数据来自 `app.mokahr.com` 的 Moka 招聘门户，
覆盖游戏研发、策划、美术、运营、技术等方向。
接口响应为 AES 加密，scraper 在本地解密后返回结构化字段。

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `keyword` | 否 | 搜索关键词，如 `"服务器"`、`"策划"`，服务端过滤 |
| `city` | 否 | 城市名，如 `"上海"`，本地过滤 |
| `limit` | 否 | 返回数量上限，默认 20，最大 100 |

## 调用示例

```python
fetch_company_jobs(company="shengqu", params='{"keyword":"服务器","city":"上海","limit":10}')
```

返回结果中的 `url` 形如：

```text
https://app.mokahr.com/apply/shengqu/4077#/job/<jobId>
```

可直接传给 `fetch_jd_detail`。

## 返回字段

列表：`title`、`url`、`company`、`location`、`department`、`summary`、
`job_id`、`source`。

详情：`title`、`company`、`location`、`department`、`salary`、
`description`、`requirements`、`job_type`、`source`。

## 注意事项

- 本源为盛趣游戏社招 Moka 门户，不公开薪资，`salary` 通常为空。
- 关键词为服务端过滤，城市为本地过滤。
- 详情页为 SPA，scraper 直接调用 Moka 详情接口并解密，无需浏览器；
  也可先 `search` 拿到 `url` 再 `get_detail`，或直接用列表返回的 url 取详情。
- 站点路径为 `/apply/` 形式，与 `/social-recruitment/` 门户等价。
