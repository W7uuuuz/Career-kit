# 米哈游 使用指南

## 用途

搜索米哈游社会招聘岗位。数据来自 `jobs.mihoyo.com` 前端使用的公开 ATS 接口
`ats.openout.mihoyo.com/ats-portal`，无需登录；详情接口返回职位描述与任职要求。
不公开薪资。

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| keyword | 否 | 岗位名称关键词，如 `"原画"`、`"后端"`；为空时拉取全量 |
| city | 否 | 城市名，如 `"上海"`、`"北京"`；优先服务端按地点筛选 |
| limit | 否 | 返回数量上限，默认 20，最大 100（接口每页最多 50 条） |

## 调用示例

```
fetch_company_jobs(company="mihoyo", params='{"keyword":"原画","city":"上海","limit":10}')
```

## 返回字段

| 字段 | 说明 |
|------|------|
| title | 岗位名称 |
| url | 岗位详情链接 |
| company | 米哈游 |
| location | 工作城市 |
| department | 职能类型 |
| summary | 岗位摘要 / 标签 / 项目 |
| job_id | 米哈游岗位 id |
| job_type | 全职 / 第三方编制等 |
| project | 招聘项目 |
| tags | 岗位标签 |
| source | mihoyo |

`fetch_jd_detail` 返回 `description`、`requirements`、`location`、`department`、
`project` 等字段。

## 注意事项

1. 列表接口为 `POST /ats-portal/v1/job/list`，请求体含
   `competencyTypes`、`pageNo`、`pageSize`、`channelDetailIds`、`hireType`。
2. 详情接口为 `POST /ats-portal/v1/job/info`，请求体含 `id`、
   `channelDetailIds`、`hireType`。
3. 当前接入社会招聘（`hireType=0`）；城市名会先通过地址枚举解析成 `addressIds`，
   解析失败时退回本地过滤。
4. 详情页 URL 形如 `https://jobs.mihoyo.com/position#/position/<job_id>`。

## 错误处理

| 错误 | 原因 | 解决 |
|------|------|------|
| 米哈游接口请求失败 | 网络波动或 ATS 接口临时不可用 | 稍后重试 |
| 米哈游接口返回格式异常 | 接口结构变化 | 检查 ATS 接口 |
| 米哈游详情返回错误 | 岗位 id 无效或岗位已下线 | 重新搜索后获取最新链接 |
