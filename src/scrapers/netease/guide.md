# 网易 使用指南

## 用途
搜索网易社会招聘岗位。数据来自 `hr.163.com` 的公开 JSON 接口，无需登录。
当前只接入社招，不公开薪资。

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| keyword | 否 | 搜索关键词，如 `"Java"`、`"AI"` |
| city | 否 | 城市名，如 `"杭州"`、`"北京"`；对结果做本地过滤 |
| limit | 否 | 返回数量上限，默认 20，最大 100 |

## 调用示例

```
fetch_company_jobs(company="netease", params='{"keyword":"Java","city":"杭州","limit":10}')
```

## 返回字段

| 字段 | 说明 |
|------|------|
| title | 岗位名称 |
| url | 岗位详情链接 |
| company | 网易 |
| location | 工作城市 |
| department | 部门 |
| summary | 岗位描述摘要 |
| job_id | 网易岗位 id |
| job_type | 岗位类别 |
| education | 学历要求 |
| experience | 工作经验要求 |
| source | netease |

## 注意
- 列表响应已包含岗位描述与任职要求；`fetch_jd_detail` 使用搜索时的列表快照。
- 未找到列表快照时，请先重新 `fetch_company_jobs`。
