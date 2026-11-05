# 美团 使用指南

## 用途
搜索美团社会招聘岗位。数据来自 `zhaopin.meituan.com` 的公开 JSON 接口，
无需登录。当前只接入社招（jobType code 3），不公开薪资。

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| keyword | 否 | 搜索关键词，如 `"AI"`、`"后端"`；为空时拉取全量 |
| city | 否 | 城市名，如 `"北京"`、`"上海"`；服务端过滤并做本地兜底 |
| limit | 否 | 返回数量上限，默认 20，最大 100 |

## 调用示例

```
fetch_company_jobs(company="meituan", params='{"keyword":"AI","city":"北京","limit":10}')
```

## 返回字段

| 字段 | 说明 |
|------|------|
| title | 岗位名称 |
| url | 岗位详情链接 |
| company | 美团 |
| location | 工作城市 |
| department | 部门 |
| summary | 岗位职责与要求摘要 |
| job_id | 美团 jobUnionId |
| source | meituan |

## 注意
- 列表响应已包含岗位职责与要求；`fetch_jd_detail` 使用搜索时的列表快照。
- 未找到列表快照时，请先重新 `fetch_company_jobs`。
