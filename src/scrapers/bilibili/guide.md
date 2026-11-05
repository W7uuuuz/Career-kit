# 哔哩哔哩 使用指南

## 用途
搜索哔哩哔哩社会招聘岗位。数据来自 `jobs.bilibili.com`，接口需要页面生成的
csrf / lunar-id 请求头，因此本数据源使用 Playwright 打开页面并拦截列表响应。
当前只接入社招，不公开薪资。

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| keyword | 否 | 搜索关键词，如 `"Java"`、`"算法"` |
| city | 否 | 城市名，如 `"上海"`；对结果做本地过滤 |
| limit | 否 | 返回数量上限，默认 10，最大 30（每页 10 条） |

## 调用示例

```
fetch_company_jobs(company="bilibili", params='{"keyword":"Java","city":"上海","limit":10}')
```

## 返回字段

| 字段 | 说明 |
|------|------|
| title | 岗位名称 |
| url | 岗位详情链接 |
| company | 哔哩哔哩 |
| location | 工作城市 |
| department | 职位类别 |
| summary | 岗位描述摘要 |
| job_id | B站岗位 id |
| job_type | 岗位类型 |
| publish_time | 发布时间 |
| source | bilibili |

## 注意
- 首次使用前需要执行 `playwright install chromium`。
- 列表响应已包含岗位描述；`fetch_jd_detail` 使用搜索时的列表快照。
- 页面结构或请求头逻辑变化时，抓取会返回可诊断错误，不会编造岗位。
