# 蚂蚁集团 使用指南

## 用途
搜索蚂蚁集团社会招聘岗位。数据来自 `talent.antgroup.com`，接口需要页面
cookie 中的 `ctoken`，因此本数据源使用 Playwright 打开页面后在页面上下文内
调用接口。当前只接入社招，不公开薪资。

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| keyword | 否 | 搜索关键词，如 `"Java"`、`"算法"` |
| city | 否 | 城市名，如 `"杭州"`；对结果做本地过滤 |
| limit | 否 | 返回数量上限，默认 20，最大 100 |

## 调用示例

```
fetch_company_jobs(company="ant", params='{"keyword":"Java","city":"杭州","limit":10}')
```

## 返回字段

| 字段 | 说明 |
|------|------|
| title | 岗位名称 |
| url | 岗位详情链接 |
| company | 蚂蚁集团 |
| location | 工作城市 |
| department | 职位类别 |
| summary | 岗位职责与要求摘要 |
| job_id | 蚂蚁 positionId |
| publish_time | 发布时间 |
| source | ant |

## 注意
- 首次使用前需要执行 `playwright install chromium`。
- 列表响应已包含岗位职责与要求；`fetch_jd_detail` 使用搜索时的列表快照。
- 页面结构或 ctoken 机制变化时，抓取会返回可诊断错误，不会编造岗位。
