# 企业库

> Career Kit 已收录的企业数据源。教程的唯一事实源是各 scraper 包内的 `guide.md`。

## 已收录企业

| ID | 名称 | 数据类型 | 支持渠道 | 使用教程 |
|----|------|----------|----------|----------|
| `boss` | BOSS直聘 | JD（含薪资） | 社招 | [guide](../src/scrapers/boss/guide.md) |
| `bytedance` | 字节跳动 | JD | 社招 / 校招 | [guide](../src/scrapers/bytedance/guide.md) |
| `tencent` | 腾讯 | JD | 社招 / 校招 / 实习 | [guide](../src/scrapers/tencent/guide.md) |
| `baidu` | 百度 | JD | 社招 / 校招 / 实习 | [guide](../src/scrapers/baidu/guide.md) |
| `alibaba` | 阿里巴巴 | JD | 校招 / 实习 | [guide](../src/scrapers/alibaba/guide.md) |
| `nowcoder` | 牛客网 | 面经 | 面经 | [guide](../src/scrapers/nowcoder/guide.md) |

> `get_scraper_guide(company)` 运行时读取同一份 guide.md。新增企业时在包内附
> guide.md 即自动生效（模板见 `_template/guide.md`）。

## 使用流程

```
1. list_data_sources()                                  # 查看可用企业和参数
2. get_scraper_guide(company)                           # 首次使用前读教程
3. fetch_company_jobs(company="boss", params='{"keyword":"Python"}')
4. fetch_jd_detail(url="https://...")                   # 获取详情
```

## 通用参数

| 参数 | 说明 | 示例 |
|------|------|------|
| `keyword` | 搜索关键词 | `"Python"`, `"AI Agent"` |
| `city` | 城市名 | `"上海"`, `"北京"` |
| `scope` | 招聘类型（新增源支持） | `"social"`, `"campus"`, `"intern"` |
| `limit` | 返回数量上限 | `10`, `20` |

各源实际支持的参数以 `list_data_sources` 返回为准；`params` 只传列出的参数。

## 数据用途

| 数据类型 | 用途 | 使用场景 |
|----------|------|----------|
| JD | 了解岗位要求 | 差距分析、路线图规划 |
| 面经 | 了解面试内容 | 面试准备、技能补充 |
| 薪资 | 了解市场行情 | 目标设定、期望管理（并非所有源公开） |

## 参考实现

新增腾讯/百度/阿里 scraper 时参考了以下开源项目（代码注释中保留具体出处）：

- [HA7CH/job-pro](https://github.com/HA7CH/job-pro)：腾讯校招接口、阿里 batch/CSRF 流程
- [Enzoding/JobHunt-CLI](https://github.com/Enzoding/JobHunt-CLI)：多站点统一字段与渠道映射
- [Nanaeo/RecruitSpider](https://github.com/Nanaeo/RecruitSpider)：腾讯/百度早期实现

## 贡献新 Scraper

1. 复制模板：`cp -r src/scrapers/_template src/scrapers/{company}`
2. 实现 `search()` / `get_detail()`，声明 `PARAMS`
3. 填写包内 `guide.md`（缺文件会挂测试）
4. 在 `src/scrapers/config.yaml` 注册
5. 提交 PR

详见 [CONTRIBUTING.md](../CONTRIBUTING.md)。
