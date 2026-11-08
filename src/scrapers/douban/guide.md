# 豆瓣 使用指南

## 用途

搜索豆瓣社会招聘、校园招聘与实习生招聘岗位。数据来自 `jobs.douban.com` 的静态 HTML，
无需登录。岗位列表与详情在同一页面内（锚点 `#position-<code>`），不公开薪资。

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| keyword | 否 | 搜索关键词，如 `"算法"`、`"运营"`、`"Android"`；匹配标题/职责/要求 |
| city | 否 | 城市名，如 `"北京"`、`"天津"`；对结果做本地过滤 |
| job_type | 否 | `social`（社招）/ `campus`（校招）/ `intern`（实习）/ `all`（默认全部） |
| limit | 否 | 返回数量上限，默认 20，最大 100 |

## 调用示例

```
fetch_company_jobs(company="douban", params='{"keyword":"运营","job_type":"intern","limit":10}')
```

返回的 `url` 形如：

```text
https://jobs.douban.com/jobs/intern/#position-ydkfsxs
```

可直接传给 `fetch_jd_detail`，详情来自同页的岗位正文。

## 返回字段

| 字段 | 说明 |
|------|------|
| title | 岗位名称 |
| url | 岗位锚点链接 |
| company | 豆瓣 |
| location | 工作城市（北京 / 天津） |
| department | 部门或子公司（研发/运营等） |
| summary | 职责或要求摘要 |
| description | 职位描述 |
| requirements | 职位要求 |
| benefits | 优先条件 / 加分项 |
| job_id | 页面岗位锚点 code |
| job_type | social / campus / intern |
| source | douban |

## 注意事项

- 页面为服务端渲染，`search` 会同时抓取社招、校招、实习三个入口（可用 `job_type` 限定）。
- 详情必须带 `#position-<code>` 锚点；没有锚点会返回提示。
- 工作地点默认按页面说明推断：研发/运营类为北京，天津兆维岗位为天津。
- 不公开薪资，`salary` 为空。
