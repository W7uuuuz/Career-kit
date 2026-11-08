# 知乎社会招聘

## 用途

知乎社会招聘 JD。数据来自 `app.mokahr.com` 的 Moka 招聘门户，
列表接口返回 AES-CBC 加密数据，scraper 在本地解密后返回结构化字段，
适合做岗位要求分析和差距对比。

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `keyword` | 否 | 搜索关键词，如 `"算法"`、`"后端"`、`"产品"`，服务端过滤 |
| `city` | 否 | 城市名，如 `"北京"`、`"上海"`，本地过滤 |
| `limit` | 否 | 返回数量上限，默认 20，最大 100 |

## 调用示例

```python
fetch_company_jobs(company="zhihu", params='{"keyword":"算法","city":"北京","limit":10}')
```

返回结果中的 `url` 形如：

```text
https://app.mokahr.com/apply/zhihu/78336#/job/<jobId>
```

可直接传给 `fetch_jd_detail`。

## 返回字段

列表：`title`、`url`、`company`、`location`、`department`、`summary`、
`job_id`、`source`。

详情：`title`、`company`、`location`、`department`、`salary`、
`description`、`requirements`、`job_type`、`source`。

## 注意事项

- 门户入口 `https://app.mokahr.com/apply/zhihu` 会跳转到带 siteId 的
  `https://app.mokahr.com/apply/zhihu/78336`，站点参数以跳转后为准。
- 不公开薪资，`salary` 通常为空。
- `keyword` 为服务端过滤，`city` 为本地过滤。
- 详情页为 SPA，scraper 直接调用 Moka 详情接口并解密，无需浏览器。
- 解密依赖 `cryptography`（已在项目依赖中声明）。
