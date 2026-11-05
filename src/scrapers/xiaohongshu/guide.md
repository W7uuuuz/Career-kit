# 小红书 使用指南

## 用途
搜索小红书社会招聘岗位。数据来自 `job.xiaohongshu.com` 的公开 JSON 接口，
无需登录。当前只接入社招，不公开薪资。

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| keyword | 否 | 搜索关键词，如 `"Java"`、`"AI"` |
| city | 否 | 城市名，如 `"上海"`、`"北京"`；对结果做本地过滤 |
| limit | 否 | 返回数量上限，默认 20，最大 100 |

## 调用示例

```
fetch_company_jobs(company="xiaohongshu", params='{"keyword":"Java","city":"上海","limit":10}')
```

## 返回字段

| 字段 | 说明 |
|------|------|
| title | 岗位名称 |
| url | 岗位详情链接 |
| company | 小红书 |
| location | 工作城市 |
| department | 方向/岗位类别 |
| summary | 岗位职责与要求摘要 |
| job_id | 小红书 positionId |
| job_type | 岗位类型 |
| publish_time | 发布时间 |
| source | xiaohongshu |

## 注意
- 列表响应已包含岗位职责与要求；`fetch_jd_detail` 使用搜索时的列表快照。
- 未找到列表快照时，请先重新 `fetch_company_jobs`。
