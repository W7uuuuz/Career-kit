# Shopee 使用指南

## 用途

搜索 Shopee 全球招聘岗位。数据来自 `careers.shopee.cn` 背后的 Workatsea ATS
公开接口（`ats.workatsea.com/ats/api/v1/user/...`），无需登录、无需签名。
列表已含 JD 正文，详情接口提供完整岗位描述与要求。不公开薪资。

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| keyword | 否 | 搜索关键词，如 `"engineer"`、`"Python"`；为空时拉取全量 |
| city | 否 | 城市名，如 `"Shanghai"`、`"上海"`；自动映射为 city_ids |
| department | 否 | 部门名，如 `"Engineering and Technology"`；自动映射为 department_ids |
| limit | 否 | 返回数量上限，默认 20，最大 100（接口每页 50 条，自动翻页） |

## 调用示例

```
fetch_company_jobs(company="shopee", params='{"keyword":"engineer","limit":10}')
fetch_company_jobs(company="shopee", params='{"city":"Singapore","limit":10}')
fetch_company_jobs(company="shopee", params='{"department":"Engineering and Technology"}')
```

## 返回字段

| 字段 | 说明 |
|------|------|
| title | 岗位名称 |
| url | 详情页链接（`https://careers.shopee.cn/job-detail/<job_id>/1`） |
| company | Shopee |
| location | 城市与国家/地区，如 `"Shanghai, China"` |
| department | 部门名称 |
| summary | 岗位描述与要求摘要 |
| job_id | Shopee 岗位 id（J 开头） |
| source | shopee |

## 注意

- 接口默认覆盖全球站点；前端会隐藏 Taipei（region_id=28），本源同样过滤。
- `city`/`department` 先按名称精确匹配，再退化为包含匹配；无法匹配时 `city` 做本地过滤。
- 详情接口需要 `job_id`（J 开头字符串），不是数字 `id`。

## 错误处理

| 错误 | 原因 | 解决 |
|------|------|------|
| Shopee 接口请求失败 | 网络波动或限流 | 稍后重试；接口公开无需登录 |
| 无法从 URL 提取 Shopee 岗位 id | URL 不含 J 开头 id 或数字 id | 使用 `fetch_company_jobs` 返回的原始链接 |
| 未找到相关岗位 | 关键词/城市/部门组合无结果 | 放宽关键词或去掉筛选条件 |
