# OPPO 使用指南

## 用途

搜索 OPPO 官方招聘岗位。数据来自 `careers.oppo.com` 的公开 JSON 接口
（`/openapi/position/pageNew`），无需登录、无需签名。接口当前返回官网在招的
校园招聘/国际化招聘/博士生等项目岗位（200+ 条），列表响应已含岗位职责与要求。
不公开薪资。

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| keyword | 否 | 搜索关键词，如 `"算法"`、`"软件"`；为空时拉取全量 |
| city | 否 | 城市名，如 `"深圳市"`、`"东莞市"`；自动映射为 workCityCode |
| limit | 否 | 返回数量上限，默认 20，最大 100（接口每页 20 条，自动翻页） |

## 调用示例

```
fetch_company_jobs(company="oppo", params='{"keyword":"算法","limit":10}')
fetch_company_jobs(company="oppo", params='{"city":"深圳市","limit":10}')
```

## 返回字段

| 字段 | 说明 |
|------|------|
| title | 岗位名称 |
| url | 岗位详情页（`https://careers.oppo.com/university/oppo/campus/post/<id>`） |
| company | OPPO |
| location | 工作城市，如 `"深圳市"` |
| department | 职位类别，如 `"硬件类"` |
| summary | 岗位职责与技能要求摘要 |
| job_id | OPPO 岗位 id（idRecruitPosition） |
| project | 招聘项目，如 `"2027届博士生招聘"` |
| recruitment_type | 招聘类型，如 `"博士生"`、`"应届生"`、`"实习生"` |
| publish_time | 发布日期 |
| source | oppo |

## 注意

- 官网「校园招聘」与「社会招聘」为两套入口；当前对外公开可抓的岗位列表由
  `pageNew` 接口提供（以校园/国际化/博士生等项目岗位为主）。
- `city` 通过 `chnCityList` 映射为城市编码后再服务端过滤，匹配不到时本地兜底。
- `fetch_jd_detail` 使用 `position/detail?id=<id>`；接口不可用时回退列表快照。

## 错误处理

| 错误 | 原因 | 解决 |
|------|------|------|
| OPPO 接口请求失败 | 网络波动或限流 | 稍后重试；接口公开无需登录 |
| 无法从 URL 提取 OPPO 岗位 id | URL 路径末段不是数字 | 使用 `fetch_company_jobs` 返回的原始链接 |
| 未找到相关岗位 | 关键词/城市组合无结果 | 放宽关键词或去掉城市筛选 |
