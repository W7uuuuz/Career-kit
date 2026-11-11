# 实习僧 使用指南

## 用途

实习僧（shixiseng.com）是第三方实习岗位聚合平台，覆盖大量金融机构、咨询、互联网和制造企业的日常实习。
适合补充企业官网未公开的实习机会，也适合观察「投行/行研/量化/风控」等方向的实习要求。
数据来自公开列表页与详情页，只取近一月刷新的岗位；不登录、不绕过验证码。

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `keyword` | 是 | 搜索关键词，如 `"量化"`、`"投行"`、`"中金"` |
| `city` | 否 | 城市名，如 `"北京"`、`"上海"`；默认全国 |
| `page` | 否 | 页码，默认 1 |
| `limit` | 否 | 返回数量上限，默认 20，最大 100 |

## 调用示例

```python
fetch_company_jobs(company="shixiseng", params='{"keyword":"量化","city":"上海","limit":10}')
```

返回结果中的 `url` 形如 `https://www.shixiseng.com/intern/inn_xxx`，可直接传给 `fetch_jd_detail` 获取岗位描述与投递要求。

## 返回字段

列表：`title`、`url`、`company`、`location`、`salary`、`department`、`summary`、`job_type`、`job_id`、`source`。

详情：`title`、`company`、`location`、`address`、`salary`、`degree` / `education`、`industry`、`weekly_days`、`duration_months`、`deadline`、`chance`、`description`、`requirements`、`skills`、`tags`、`benefits`、`job_type`、`source`、`url`、`updated_at`。

## 注意事项

1. 只收录近一月刷新（`publishTime=mon`）的实习岗位；搜索为空时可能是该方向近期没有新岗位。
2. 列表页内嵌 `__NUXT__` 数据保留明文日薪、学历和标签，scraper 优先用它；标题等被自定义字体替换的字符通过公开字体的 glyph 名还原，遇到未知字符才剥离。
3. 列表页不逐条补详情，避免高频请求；需要 JD 全文时用 `fetch_jd_detail`。
4. 详情页部分内容需要登录才能投递，但岗位描述与投递要求匿名可读；若页面改版会如实报错。
5. 请保持低频访问；站点机器人协议与用户协议未见禁止性条款，如站点提出异议应停用该源。

## 错误处理

| 错误 | 原因 | 解决 |
|------|------|------|
| `实习僧搜索需要提供 keyword` | 未传关键词 | 传入方向词或公司名，如 `"行研"`、`"中信证券"` |
| `未找到与「...」相关的实习岗位` | 近一月无匹配岗位或关键词过窄 | 换更宽的方向词、去掉城市限制或稍后重试 |
| `实习僧搜索页抓取失败` | 网络、限流或站点改版 | 稍后重试；持续失败时如实告知用户并改用 BOSS/企业源 |
| `详情页结构已变化` | 页面改版或需要登录 | 改用列表页摘要，或让用户手动打开链接 |
