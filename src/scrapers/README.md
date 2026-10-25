# 企业库

社区驱动的企业招聘数据源。企业清单、通用参数与贡献流程以
[docs/scrapers.md](../../docs/scrapers.md) 为唯一事实源；本文件只保留源索引。

## 已注册企业（6）

| ID | 名称 | 数据类型 | 支持渠道 |
|----|------|----------|----------|
| `boss` | BOSS直聘 | JD（含薪资） | 社招 |
| `bytedance` | 字节跳动 | JD | 社招 / 校招 |
| `tencent` | 腾讯 | JD | 社招 / 校招 / 实习 |
| `baidu` | 百度 | JD | 社招 / 校招 / 实习 |
| `alibaba` | 阿里巴巴 | JD | 校招 / 实习 |
| `nowcoder` | 牛客网 | 面经 | 面经 |

每个源的完整教程是同目录下的 `guide.md`（`get_scraper_guide` 与 MCP Resource 同源）。

## 使用流程

```
list_data_sources() → get_scraper_guide(company) → fetch_company_jobs(...) → fetch_jd_detail(url)
```

## 贡献新 Scraper

复制 `_template/`，实现 `search()` / `get_detail()`，声明 `PARAMS`，填写 `guide.md`，
并在 `config.yaml` 注册。详见 [CONTRIBUTING.md](../../CONTRIBUTING.md)。
