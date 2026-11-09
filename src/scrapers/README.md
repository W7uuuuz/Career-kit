# 企业数据源

社区驱动的企业招聘数据源。单一事实源：
- 注册 = `config.yaml`
- 企业元数据与别名 = `companies.yaml`（查询入口 `catalog.get_company`）
- 参数 = 各源 `scraper.py` 的 `PARAMS`
- 教程 = 各源包内的 `guide.md`

本文件与 [docs/scrapers.md](../../docs/scrapers.md) 只做索引与链接，不复制通用参数表。
企业档位（大厂 / 中厂 / 小厂）、行业、别名与 scraper 映射见 `companies.yaml`；
查询入口是 `catalog.py`（`list_companies` / `get_company` / `tier_for_scraper`）。
企业目录收录 68 家，其中 54 家可自动抓取；其余标注为需手动投递。

## 已注册企业（58）

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
| `dji` | 大疆 | JD | 社招 |
| `yoozoo` | 游族网络 | JD | 社招 |
| `shengqu` | 盛趣游戏 | JD | 社招 |
| `zuoyebang` | 作业帮 | JD | 社招 |
| `giant` | 巨人网络 | JD | 社招 |
| `mgtv` | 芒果TV | JD | 社招 |
| `yuanfudao` | 猿辅导 | JD | 校招/实习 |
| `keep` | Keep | JD | 社招 |
| `hello` | 哈啰 | JD | 社招 |
| `zhihu` | 知乎 | JD | 社招 |
| `iqiyi` | 爱奇艺 | JD | 社招 |
| `papergames` | 叠纸游戏 | JD | 社招 |
| `maimai` | 脉脉 | JD | 社招 |
| `minimax` | MiniMax | JD | 社招 |
| `soul` | Soul | JD | 社招 |
| `lilith` | 莉莉丝 | JD | 社招 |
| `dewu` | 得物 | JD | 社招 |
| `sensetime` | 商汤科技 | JD | 社招 |
| `vip` | 唯品会 | JD | 社招 |
| `sanqi` | 三七互娱 | JD | 社招 |
| `tal` | 好未来 | JD | 校招/实习 |
| `mihoyo` | 米哈游 | JD | 社招 |
| `tongcheng` | 同程旅行 | JD | 社招 |
| `youzan` | 有赞 | JD | 社招 |
| `megvii` | 旷视科技 | JD | 社招 |
| `shein` | SHEIN | JD（不公开薪资） | 社招 / 校招 / 实习 |
| `shopee` | Shopee | JD | 社招 |
| `oppo` | OPPO | JD（不公开薪资） | 校招 / 国际化 / 博士项目 |
| `vivo` | vivo | JD | 社招 |
| `douban` | 豆瓣 | JD | 社招/校招/实习 |
| `momo` | 陌陌 | JD | 社招 |
| `nowcoder` | 牛客网 | 面经 | — |
| `github` | GitHub 经验帖 | 成功经验/面经（issue 帖） | — |

每个源的完整教程是同目录下的 `guide.md`（`get_scraper_guide` 与 MCP Resource 同源）。

## 使用流程

```
list_data_sources() → get_scraper_guide(company) → fetch_company_jobs(...) → fetch_jd_detail(url)
```

## 贡献新 Scraper

复制 `_template/`，实现 `search()` / `get_detail()`，声明 `PARAMS`，填写 `guide.md`，
在 `config.yaml` 注册，并在 `companies.yaml` 补充档位、行业、别名与 scraper 映射。
详见 [CONTRIBUTING.md](../../CONTRIBUTING.md)。
