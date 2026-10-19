# 腾讯 使用指南

## 用途

搜索腾讯社招、校招与实习岗位。社招来自 `careers.tencent.com`，校招/实习来自
`join.qq.com`，两个站点均为公开接口。腾讯不公开薪资，返回结果 `salary` 为空。

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| keyword | 否 | 搜索关键词，如 `"AI"`、`"后端"` |
| city | 否 | 城市名，如 `"深圳"`、`"北京"`；未匹配到城市码时不加过滤 |
| scope | 否 | `social`=社招（默认）、`campus`=校招、`intern`=实习 |
| limit | 否 | 返回数量上限，默认 20，最大 100 |

## 调用示例

```
fetch_company_jobs(company="tencent", params='{"keyword":"AI","city":"深圳","scope":"social","limit":10}')
fetch_company_jobs(company="tencent", params='{"keyword":"算法","scope":"intern","limit":10}')
```

## 返回字段

| 字段 | 说明 |
|------|------|
| title | 岗位名称 |
| url | 详情页链接（可传给 `fetch_jd_detail`） |
| location | 工作城市 |
| department | 事业群（社招）或项目组（校招） |
| summary | 职责摘要 / 招聘项目 |
| salary | 空（腾讯不公开薪资） |

## 注意事项

1. 社招与校招是两套站点：`scope=social` 走 `careers.tencent.com`，
   `scope=campus/intern` 走 `join.qq.com`
2. 校招/实习的 scope 通过 `getProjectMapping` 动态解析，不硬编码项目 ID
3. 详情页 URL 会被自动路由；社招与校招分别使用各自的详情接口
4. 接口失败时返回明确错误，不要编造岗位或薪资
