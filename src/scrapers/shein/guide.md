# SHEIN 使用指南

## 用途

搜索 SHEIN 全球招聘岗位。数据来自 `careers.shein.com` 官方公开 JSON 接口
（`/api/v1/open/grw/front/jobPage`），无需登录、无需签名，覆盖社招、校招与实习。
不公开薪资。

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| keyword | 否 | 搜索关键词，如 `"engineer"`、`"算法"`；为空时拉取全量 |
| city | 否 | 城市名，如 `"Shanghai"`、`"深圳市"`；服务端按 cityName 过滤 |
| job_type | 否 | 招聘类型：`social`（社招）、`campus`（校招）、`intern`（实习）；为空时全部 |
| limit | 否 | 返回数量上限，默认 20，最大 100（接口每页 10 条，自动翻页） |

## 调用示例

```
fetch_company_jobs(company="shein", params='{"keyword":"engineer","job_type":"social","limit":10}')
fetch_company_jobs(company="shein", params='{"keyword":"算法","city":"深圳市","limit":10}')
```

## 返回字段

| 字段 | 说明 |
|------|------|
| title | 岗位名称 |
| url | 岗位落地页（自有 Avature 或 Greenhouse 链接） |
| company | SHEIN |
| location | 城市与国家，如 `"Toronto, Canada"` |
| department | 职位类别，如 `"Information Technology"` |
| summary | 岗位描述摘要 |
| job_id | SHEIN 岗位 id |
| job_type | 招聘类型 id（SOCIAL / CAMPUS / PRACTICE） |
| publish_time | 发布日期 |
| source | shein |

## 注意

- 列表响应已包含完整岗位描述；`fetch_jd_detail` 会用 `jobIds` 过滤实时拉取单条，
  接口不可用时回退到搜索时的列表快照。
- 岗位落地页可能指向 Greenhouse 等外部 ATS，此时请携带 `company="shein"`
  调用详情，避免 URL 自动路由失败。

## 错误处理

| 错误 | 原因 | 解决 |
|------|------|------|
| SHEIN 接口请求失败 | 网络波动或接口限流 | 稍后重试；接口为公开 JSON，无需登录 |
| 无法从 URL 提取 SHEIN 岗位 id | URL 中既无 `jobId` 参数也无数字路径 | 使用 `fetch_company_jobs` 返回的原始链接 |
| 未找到相关岗位 | 关键词/城市组合无结果 | 放宽关键词或去掉城市筛选 |
