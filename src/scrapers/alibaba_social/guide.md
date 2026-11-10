# 阿里巴巴（社招） 使用指南

## 用途
搜索阿里巴巴集团社会招聘岗位。数据来自 `talent.alibaba.com` 的公开 JSON 接口，
接口有 stateless CSRF 校验：请求携带同值的 `XSRF-TOKEN` cookie 与
`x-xsrf-token` header 即可，不需要登录。当前只接入社招，不公开薪资。

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| keyword | 否 | 搜索关键词，如 `"Java"`、`"AI"` |
| city | 否 | 城市名，如 `"杭州"`；对结果做本地过滤 |
| limit | 否 | 返回数量上限，默认 20，最大 100 |

## 调用示例

```
fetch_company_jobs(company="alibaba_social", params='{"keyword":"Java","city":"杭州","limit":10}')
```

## 返回字段

| 字段 | 说明 |
|------|------|
| title | 岗位名称 |
| url | 岗位详情链接 |
| company | 阿里巴巴 |
| location | 工作城市 |
| department | 职位类别 |
| summary | 岗位职责与要求摘要 |
| job_id | 阿里 positionId |
| experience | 经验要求 |
| publish_time | 发布时间 |
| source | alibaba_social |

## 注意
- 列表响应已包含岗位职责与要求；`fetch_jd_detail` 使用搜索时的列表快照。
- 未找到列表快照时，请先重新 `fetch_company_jobs`。
- 校招/实习见 `alibaba`，调用 `fetch_company_jobs(company="alibaba", params=...)` 查询。
