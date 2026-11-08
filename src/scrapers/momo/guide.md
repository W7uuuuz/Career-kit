# 陌陌 使用指南

## 用途

搜索陌陌（Hello Group）社会招聘岗位。数据来自 `www.immomo.com/jobs/join/index`
的静态 HTML，无需登录。岗位列表与详情在同一页面内以手风琴展开，不公开薪资。

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| keyword | 否 | 搜索关键词，如 `"Android"`、`"产品"`、`"设计"`；匹配标题/类别/正文 |
| city | 否 | 工作地点，如 `"北京"`、`"上海"`；对结果做本地过滤 |
| job_type | 否 | 岗位类别，如 `"技术类"`、`"设计类"`；对类别做本地过滤 |
| limit | 否 | 返回数量上限，默认 20，最大 100 |

## 调用示例

```
fetch_company_jobs(company="momo", params='{"keyword":"设计","limit":10}')
```

返回的 `url` 形如：

```text
https://www.immomo.com/jobs/join/index#job-<岗位标题>
```

可直接传给 `fetch_jd_detail`，详情来自同页展开的岗位正文。

## 返回字段

| 字段 | 说明 |
|------|------|
| title | 岗位名称 |
| url | 页面岗位锚点链接 |
| company | 陌陌 |
| location | 工作地点 |
| department | 岗位类别 |
| job_type | 岗位类别 |
| summary | 岗位正文摘要 |
| description | 岗位描述 |
| requirements | 任职要求 |
| publish_time | 发布时间 |
| job_id | 岗位标题（页面无独立 id） |
| source | momo |

## 注意事项

- 页面服务端渲染首批岗位，scraper 直接解析静态 HTML，不需要浏览器。
- 站点分页 AJAX 只对存在岗位的类别返回数据，空类别返回 `ec=406`；当前公开岗位通过静态页面即可完整获取。
- 岗位详情没有独立 URL，使用标题锚点定位；标题相同可能产生歧义。
- 不公开薪资，`salary` 为空。
- 陌陌当前公开岗位较少，搜索无结果时属正常现象。
