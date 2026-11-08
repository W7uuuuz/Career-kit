# 有赞 使用指南

## 用途

有赞社会招聘（`job.youzan.com/careers`）的 Supabase 公开 function 接口。列表即含岗位描述与任职要求，适合互联网社招岗位分析与投递清单。

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| keyword | 否 | 搜索关键词（如 "后端"、"产品经理"） |
| city | 否 | 城市名（如 "杭州市"）；服务端过滤并做本地兜底 |
| limit | 否 | 返回数量上限，默认 20，最大 100 |

## 调用示例

```
fetch_company_jobs(company="youzan", params='{"keyword":"产品","limit":5}')
fetch_company_jobs(company="youzan", params='{"city":"杭州市","limit":10}')
```

## 返回字段

| 字段 | 说明 |
|------|------|
| title | 岗位名称 |
| url | 详情页链接（`/careers/jobs/<jobId>`） |
| company | 有赞 |
| location | 城市，多城市以 "/" 分隔 |
| department | 所属部门 |
| salary | 薪资文案；"面议" 视为未公开，返回空 |
| summary | 岗位描述摘要 |
| job_type | 用工类型（如 "全职"） |
| is_urgent | 是否急招 |
| publish_time | 发布时间 |
| job_id | 岗位 ID（uuid） |

## 接口说明

- 列表与详情均为 `POST https://rassfvy0pfpl2qutpu6v.db.superun.com/functions/v1/careers-portal`，请求体为 JSON。
- 列表：`{"action":"list","keyword":"","city":"","category":"","publishedWithinDays":"all","urgentOnly":false,"page":1,"pageSize":20}`。
- 详情：`{"action":"detail","jobId":"<uuid>"}`。
- 无需登录、无需 apikey；接口对浏览器来源做了 Referer 校验，已内置。

## 错误处理

| 错误 | 原因 | 解决 |
|------|------|------|
| 有赞接口请求失败 | 网络异常或 function 不可用 | 稍后重试 |
| 有赞列表接口返回错误 | 参数或接口逻辑变化 | 检查 action 与分页参数 |
| 未找到相关岗位 | 关键词/城市无匹配 | 更换关键词或城市 |
| 未找到该岗位的列表快照 | 未经 search 直接取详情且详情为空 | 先调用 search |
