# 旷视科技 使用指南

## 用途

旷视科技社会招聘。官网「加入旷视」的社会招聘入口实际跳转到 Moka 独立 ATS（`app.mokahr.com/social-recruitment/megviihr/38641`），本源通过 Moka 公开加密接口抓取岗位列表与详情，适合 AI/算法/售前等岗位分析与投递清单。

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| keyword | 否 | 搜索关键词（如 "算法"、"后端"、"售前"），服务端过滤 |
| city | 否 | 城市名（如 "北京市"、"上海市"），按详情工作地点本地过滤 |
| limit | 否 | 返回数量上限，默认 20，最大 100 |

## 调用示例

```
fetch_company_jobs(company="megvii", params='{"keyword":"算法","limit":5}')
fetch_company_jobs(company="megvii", params='{"city":"北京市","limit":10}')
```

## 返回字段

| 字段 | 说明 |
|------|------|
| title | 岗位名称 |
| url | 详情页链接（`app.mokahr.com/social-recruitment/megviihr/38641#/job/<id>`） |
| company | 旷视科技 |
| location | 工作地点（取自详情，如 "上海市"） |
| department | 所属部门 |
| summary | 岗位描述摘要 |
| job_type | 用工类型 |
| job_id | 岗位 ID |
| source | megvii |

## 接口说明

- 列表：`POST https://app.mokahr.com/api/outer/ats-apply/website/jobs/module`
- 详情：`POST https://app.mokahr.com/api/outer/ats-apply/website/job`
- 响应为 AES-CBC 加密：IV 取自门户页 `window.TurboApply.data.aesIv`，密钥来自响应字段 `necromancer`，由 `src/scrapers/_platforms/moka.py` 解密。
- 该租户列表接口只返回 id/title，因此 search 会逐条取详情补齐工作地点、摘要后再做城市过滤；结果与详情均写入缓存，重复调用不会重复请求。

## 错误处理

| 错误 | 原因 | 解决 |
|------|------|------|
| 旷视科技接口请求失败 | 网络异常或 Moka 接口不可用 | 稍后重试 |
| 旷视科技接口返回格式异常 | 加密格式或接口结构变化 | 检查 `_platforms/moka.py` 解密逻辑 |
| 未找到相关岗位 | 关键词/城市无匹配 | 更换关键词或城市 |
| 未找到该岗位的列表快照 | 未经 search 直接取详情且详情为空 | 先调用 search |
