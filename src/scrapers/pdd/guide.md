# 拼多多 使用指南

## 用途
搜索拼多多社会招聘岗位。数据来自 `careers.pddglobalhr.com` 的页面接口。
接口需要页面 JS 生成的 `anti_content` 风控参数，因此本数据源使用 Playwright
打开页面并拦截列表/详情响应。当前只接入社招，不公开薪资。

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| keyword | 否 | 搜索关键词，如 `"Java"`、`"算法"` |
| city | 否 | 城市名，如 `"上海"`、`"广州"`；对结果做本地过滤 |
| limit | 否 | 返回数量上限，默认 10，最大 30（每页 10 条） |

## 调用示例

```
fetch_company_jobs(company="pdd", params='{"keyword":"Java","city":"上海","limit":10}')
```

## 返回字段

| 字段 | 说明 |
|------|------|
| title | 岗位名称 |
| url | 岗位详情链接 |
| company | 拼多多 |
| location | 工作城市 |
| department | 岗位类别 |
| summary | 岗位类别摘要 |
| job_id | 岗位 code |
| publish_time | 更新时间 |
| source | pdd |

## 注意
- 首次使用前需要执行 `playwright install chromium`。
- 列表只返回岗位摘要；`fetch_jd_detail` 会打开详情页并抓取岗位职责、任职要求和加分项。
- 页面结构或风控逻辑变化时，抓取会返回可诊断错误，不会编造岗位。
