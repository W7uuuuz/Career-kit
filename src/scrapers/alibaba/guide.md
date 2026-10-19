# 阿里巴巴（校招/实习）使用指南

## 用途

搜索阿里巴巴集团校招与实习岗位。数据来自公开的 `campus-talent.alibaba.com`
接口，需要先获取 `XSRF-TOKEN`，再按在招批次搜索。

**范围说明**：本数据源只覆盖校招/实习。阿里社招在另一套站点，暂未接入。

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| keyword | 否 | 搜索关键词，如 `"AI"`、`"后端"` |
| city | 否 | 城市名，如 `"杭州"`、`"北京"` |
| scope | 否 | `campus`=校招（默认）、`intern`=实习、`all`=全部 |
| category | 否 | 职位类别代码（可选，原样传给 `subCategories`） |
| limit | 否 | 返回数量上限，默认 20，最大 100 |

## 调用示例

```
fetch_company_jobs(company="alibaba", params='{"keyword":"AI","city":"杭州","scope":"campus","limit":10}')
fetch_company_jobs(company="alibaba", params='{"keyword":"算法","scope":"intern","limit":10}')
```

## 返回字段

| 字段 | 说明 |
|------|------|
| title | 岗位名称 |
| url | 详情页链接（可传给 `fetch_jd_detail`） |
| location | 工作城市（可能多个） |
| department | 业务线/集团 |
| summary | 职位类别 + 招聘批次 |
| salary | 空（阿里校招不公开薪资） |

## 注意事项

1. 接口需要 `XSRF-TOKEN`：scraper 会自动 GET 校招页获取并复用
2. 搜索必须带 `batchId`；scraper 会动态发现 `graduate` / `internship` 批次
3. 多个批次会分别搜索并按岗位 ID 去重
4. 如果 `campus-talent.alibaba.com` 不可达或 token 获取失败，会返回明确错误；
   不要编造岗位数据
