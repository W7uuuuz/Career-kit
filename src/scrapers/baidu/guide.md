# 百度 使用指南

## 用途

搜索百度社招、校招与实习岗位。百度招聘接口公开、无需登录，且列表响应已包含
完整岗位职责与任职要求；`fetch_jd_detail` 会优先取详情接口，失败时回退列表快照。
百度不公开薪资，返回结果 `salary` 为空。

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| keyword | 否 | 搜索关键词，如 `"AI"`、`"算法"` |
| city | 否 | 城市名，如 `"北京"`；对 `workPlace` 做本地过滤 |
| scope | 否 | `social`=社招（默认）、`campus`=校招、`intern`=实习 |
| limit | 否 | 返回数量上限，默认 20，最大 100 |

## 调用示例

```
fetch_company_jobs(company="baidu", params='{"keyword":"AI","city":"北京","scope":"social","limit":10}')
fetch_company_jobs(company="baidu", params='{"keyword":"算法","scope":"campus","limit":10}')
```

## 返回字段

| 字段 | 说明 |
|------|------|
| title | 岗位名称 |
| url | 详情页链接（可传给 `fetch_jd_detail`） |
| location | 工作地点 |
| department | 事业群缩写 |
| summary | 岗位职责摘要 |
| salary | 空（百度不公开薪资） |

## 注意事项

1. 服务端 `pageSize` 硬上限为 20；需要更多结果时自动翻页
2. `city` 是本地过滤：会多取几页再筛选，关键词过窄时可能结果较少
3. 详情接口偶发「职位正在发布中」，此时自动回退到列表快照并标注
4. 接口失败时如实返回错误，不要编造岗位或薪资
