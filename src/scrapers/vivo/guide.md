# vivo 使用指南

## 用途

搜索 vivo 社会招聘岗位。数据来自 `hr.vivo.com` 的公开 JSON 接口，无需登录。
当前只接入社招，不公开薪资。

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| keyword | 否 | 搜索关键词，如 `"算法"`、`"Android"`、`"产品"`；由接口按标题/JD 检索 |
| city | 否 | 城市名，如 `"深圳"`、`"东莞"`、`"上海"`；对结果做本地过滤 |
| limit | 否 | 返回数量上限，默认 20，最大 100 |

## 调用示例

```
fetch_company_jobs(company="vivo", params='{"keyword":"算法","city":"深圳","limit":10}')
```

返回的 `url` 形如：

```text
https://hr.vivo.com/job-detail?_irjc=<job_category_id>&_irjid=<job_id>&_collect=false
```

可直接传给 `fetch_jd_detail`。

## 返回字段

| 字段 | 说明 |
|------|------|
| title | 岗位名称 |
| url | 岗位详情链接 |
| company | vivo |
| location | 工作城市（多城市用 `/` 分隔） |
| department | 需求部门 |
| summary | 岗位职责与要求摘要 |
| description | 岗位职责 |
| requirements | 岗位要求 |
| job_id | vivo 岗位 id |
| job_category | 岗位类别 |
| education | 学历要求 |
| experience | 工作年限要求 |
| source | vivo |

## 注意事项

- 列表接口与详情接口都返回完整 JD，`fetch_jd_detail` 会再次请求详情接口。
- 关键词由接口检索（覆盖标题与 JD）；城市为本地过滤。
- 不公开薪资，`salary` 为空。
- 单页最多取 50 条，scraper 会翻页直到满足 `limit`。
