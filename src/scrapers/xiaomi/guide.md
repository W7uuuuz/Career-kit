# 小米 使用指南

## 用途
搜索小米社会招聘岗位。数据来自 `hr.xiaomi.com` 的公开 JSON 接口，无需登录。
当前只接入社招，不公开薪资。

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| keyword | 否 | 搜索关键词，如 `"Java"`、`"AI"` |
| city | 否 | 城市名，如 `"北京"`；对结果做本地过滤 |
| limit | 否 | 返回数量上限，默认 20，最大 100 |

## 调用示例

```
fetch_company_jobs(company="xiaomi", params='{"keyword":"Java","city":"北京","limit":10}')
```

## 返回字段

| 字段 | 说明 |
|------|------|
| title | 岗位名称 |
| url | 岗位详情链接 |
| company | 小米 |
| location | 工作城市 |
| department | 一级部门 |
| summary | 岗位职责与要求摘要 |
| job_id | 小米岗位 id |
| publish_time | 发布时间 |
| source | xiaomi |

## 注意
- 列表响应已包含岗位职责与要求；`fetch_jd_detail` 使用搜索时的列表快照。
- 未找到列表快照时，请先重新 `fetch_company_jobs`。
