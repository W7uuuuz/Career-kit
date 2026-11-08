# 唯品会社会招聘

## 用途

唯品会社会招聘 JD。数据来自 `app-tc.mokahr.com` 的 Moka 独立租户门户，
覆盖产品、运营、商务、技术等方向。列表接口为明文，详情接口为 Moka AES 加密；
scraper 在本地解密后返回统一结构。

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `keyword` | 否 | 搜索关键词，如 `"算法"`、`"产品"`，服务端过滤 |
| `city` | 否 | 城市名，如 `"广州"`、`"上海"`，本地过滤 |
| `limit` | 否 | 返回数量上限，默认 20，最大 100 |

## 调用示例

```python
fetch_company_jobs(company="vip", params='{"keyword":"产品运营","city":"广州","limit":10}')
```

返回结果中的 `url` 形如：

```text
https://app-tc.mokahr.com/social-recruitment/vipshophr/10038#/job/<jobId>
```

可直接传给 `fetch_jd_detail`。

## 返回字段

列表：`title`、`url`、`company`、`location`、`department`、`summary`、
`description`、`requirements`、`job_id`、`url`、`source`。

详情：`title`、`company`、`location`、`department`、`salary`、
`description`、`requirements`、`job_type`、`job_id`、`url`、`source`。

## 注意事项

- 唯品会使用 Moka 的独立租户域名 `app-tc.mokahr.com`，与 `app.mokahr.com`
  的通用 Moka 适配器不同，因此本源单独实现；通用解密与文本清洗工具仍复用
  `_platforms/moka.py`。
- 列表接口只返回岗位标题与 id，scraper 会按需补抓详情以获取地点、职责和要求；
  `city` 过滤依赖详情里的工作地点。
- 详情接口为 AES 加密响应，无需浏览器即可解密。
- 门户不公开薪资，`salary` 通常为空。
- 详情页依赖同一租户接口；未先搜索也可直接调用详情。
