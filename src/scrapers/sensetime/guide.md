# 商汤科技社会招聘

## 用途

商汤科技（SenseTime）社会招聘 JD。数据来自飞书招聘 SaaS 门户
`hr-jobs.sensetime.com`，覆盖算法、研发、产品等方向。
搜索与详情接口的 `_signature` 由页面前端 SDK 生成，scraper 用浏览器
打开门户并捕获官方 API 响应。

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `keyword` | 否 | 搜索关键词，如 `"算法"`、`"多模态"`，服务端过滤 |
| `city` | 否 | 城市名，如 `"北京"`、`"上海"`、`"深圳"`，本地过滤 |
| `limit` | 否 | 返回数量上限，默认 20，最大 100 |

## 调用示例

```python
fetch_company_jobs(company="sensetime", params='{"keyword":"算法","city":"上海","limit":10}')
```

返回的 `url` 形如：

```text
https://hr-jobs.sensetime.com/exp/position/<jobId>/detail
```

可直接传给 `fetch_jd_detail`。

## 返回字段

列表：`title`、`url`、`company`、`location`、`department`、`summary`、
`description`、`requirements`、`job_id`、`job_type`、`publish_date`、`source`。

详情：`title`、`company`、`location`、`department`、`salary`、
`description`、`requirements`、`job_type`、`publish_date`、`url`、`source`。

## 注意事项

- 飞书招聘门户使用前端 acrawler SDK 生成 `_signature`，签名与请求参数绑定，
  无法用普通 HTTP 客户端复用；本源依赖 Playwright，优先使用系统默认
  Chrome / Edge，未检测到时回退 Playwright Chromium（需执行
  `playwright install chromium`）。
- 门户详情路径为 `/exp/position/<jobId>/detail`，与门户列表路径 `/exp/position/list` 同源。
- 门户不公开薪资，`salary` 通常为空。
- 搜索关键词为服务端过滤，城市为本地过滤；`limit` 最大 100。
- 列表响应已包含完整岗位描述与要求，详情接口用于二次确认。
- 浏览器缺失或门户结构变化时返回带企业名的错误，不会编造岗位。
