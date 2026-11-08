# 好未来 使用指南

## 用途

搜索好未来校园招聘、实习生招聘与人才计划岗位。数据来自 `job.tal.com` 与
`job-api.100tal.com` 的公开 JSON 接口，无需登录；岗位描述为 HTML 全文，
详情接口单独返回。不公开薪资。

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| keyword | 否 | 搜索关键词，如 `"AI"`、`"算法"`；为空时拉取全量 |
| city | 否 | 城市名，如 `"北京"`；对结果做本地过滤 |
| limit | 否 | 返回数量上限，默认 20，最大 100（接口每页 20 条） |

## 调用示例

```
fetch_company_jobs(company="tal", params='{"keyword":"AI","city":"北京","limit":10}')
```

## 返回字段

| 字段 | 说明 |
|------|------|
| title | 岗位名称 |
| url | 岗位详情链接 |
| company | 好未来 |
| location | 工作城市 |
| department | 所属部门 |
| summary | 岗位描述摘要 |
| job_id | 好未来岗位 UUID |
| job_type | 校招 / 实习 |
| commitment | 全职 / 实习 / 兼职 |
| category | 职能类别 |
| publish_time | 发布时间 |
| source | tal |

`fetch_jd_detail` 返回 `description`、`requirements`、`location`、`department` 等字段。

## 注意事项

1. 列表接口为 `POST /sapi/activities/c/jobs/list`，固定 `orgId=tal`、
   `route_code=kg8Meh`、`site=campus`。
2. 详情页 URL 形如 `https://job.tal.com/campus/positions/<job_id>`。
3. 岗位描述 HTML 中通常同时包含职责与任职要求，详情会按「任职要求」等标题拆分。
4. 城市仅在本地过滤，避免服务端地点参数口径不一致。

## 错误处理

| 错误 | 原因 | 解决 |
|------|------|------|
| 好未来接口请求失败 | 网络波动或接口临时不可用 | 稍后重试 |
| 好未来接口返回格式异常 | 接口结构变化 | 检查 `100tal.com` 接口 |
| 好未来详情返回错误 | 岗位 id 无效或岗位已下线 | 重新搜索后获取最新链接 |
