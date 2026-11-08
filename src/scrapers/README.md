# 企业数据源

社区驱动的企业招聘数据源。企业清单、通用参数与贡献流程以
[docs/scrapers.md](../../docs/scrapers.md) 为唯一事实源；本文件只保留源索引。

企业档位（大厂 / 中厂 / 小厂）、行业、别名与 scraper 映射见 `companies.yaml`；
查询入口是 `catalog.py`（`list_companies` / `get_company` / `tier_for_scraper`）。

## 已注册企业（27）

| ID | 名称 | 数据类型 | 支持渠道 |
|----|------|----------|----------|
| `boss` | BOSS直聘 | JD（含薪资） | 社招 |
| `bytedance` | 字节跳动 | JD | 社招 / 校招 |
| `tencent` | 腾讯 | JD | 社招 / 校招 / 实习 |
| `baidu` | 百度 | JD | 社招 / 校招 / 实习 |
| `alibaba` | 阿里巴巴 | JD | 校招 / 实习 |
| `meituan` | 美团 | JD | 社招 |
| `netease` | 网易 | JD | 社招 |
| `jd` | 京东 | JD | 社招 |
| `kuaishou` | 快手 | JD | 社招 |
| `pdd` | 拼多多 | JD | 社招 |
| `xiaohongshu` | 小红书 | JD | 社招 |
| `didi` | 滴滴 | JD | 社招 |
| `ant` | 蚂蚁集团 | JD | 社招 |
| `ctrip` | 携程 | JD | 社招 |
| `bilibili` | 哔哩哔哩 | JD | 社招 |
| `xiaomi` | 小米 | JD | 社招 |
| `alibaba_social` | 阿里巴巴（社招） | JD | 社招 |
| `boe` | 京东方 | JD | 社招 |
| `huawei` | 华为 | JD | 社招 |
| `sany` | 三一集团 | JD | 社招 |
| `crrc` | 中国中车 | JD | 社招 |
| `zhonglian` | 中联重科 | JD | 社招 |
| `inovance` | 汇川技术 | JD | 社招 |
| `tebian` | 特变电工 | JD | 社招 |
| `sungrow` | 阳光电源 | JD | 社招 |
| `nowcoder` | 牛客网 | 面经 | — |
| `github` | GitHub 经验帖 | 成功经验/面经（issue 帖） | — |

每个源的完整教程是同目录下的 `guide.md`（`get_scraper_guide` 与 MCP Resource 同源）。

## 使用流程

```
list_data_sources() → get_scraper_guide(company) → fetch_company_jobs(...) → fetch_jd_detail(url)
```

## 贡献新 Scraper

复制 `_template/`，实现 `search()` / `get_detail()`，声明 `PARAMS`，填写 `guide.md`，
并在 `config.yaml` 注册。详见 [CONTRIBUTING.md](../../CONTRIBUTING.md)。
