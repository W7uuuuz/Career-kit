# 企业数据源

> Career Kit 已收录的企业数据源。教程的唯一事实源是各 scraper 包内的 `guide.md`。

## 已收录企业

| ID | 名称 | 数据类型 | 支持渠道 | 使用教程 |
|----|------|----------|----------|----------|
| `boss` | BOSS直聘 | JD（含薪资） | 社招 | [guide](../src/scrapers/boss/guide.md) |
| `bytedance` | 字节跳动 | JD | 社招 / 校招 | [guide](../src/scrapers/bytedance/guide.md) |
| `tencent` | 腾讯 | JD | 社招 / 校招 / 实习 | [guide](../src/scrapers/tencent/guide.md) |
| `baidu` | 百度 | JD | 社招 / 校招 / 实习 | [guide](../src/scrapers/baidu/guide.md) |
| `alibaba` | 阿里巴巴 | JD | 校招 / 实习 | [guide](../src/scrapers/alibaba/guide.md) |
| `meituan` | 美团 | JD | 社招 | [guide](../src/scrapers/meituan/guide.md) |
| `netease` | 网易 | JD | 社招 | [guide](../src/scrapers/netease/guide.md) |
| `jd` | 京东 | JD | 社招 | [guide](../src/scrapers/jd/guide.md) |
| `kuaishou` | 快手 | JD | 社招 | [guide](../src/scrapers/kuaishou/guide.md) |
| `pdd` | 拼多多 | JD | 社招 | [guide](../src/scrapers/pdd/guide.md) |
| `xiaohongshu` | 小红书 | JD | 社招 | [guide](../src/scrapers/xiaohongshu/guide.md) |
| `didi` | 滴滴 | JD | 社招 | [guide](../src/scrapers/didi/guide.md) |
| `ant` | 蚂蚁集团 | JD | 社招 | [guide](../src/scrapers/ant/guide.md) |
| `ctrip` | 携程 | JD | 社招 | [guide](../src/scrapers/ctrip/guide.md) |
| `bilibili` | 哔哩哔哩 | JD | 社招 | [guide](../src/scrapers/bilibili/guide.md) |
| `xiaomi` | 小米 | JD | 社招 | [guide](../src/scrapers/xiaomi/guide.md) |
| `alibaba_social` | 阿里巴巴（社招） | JD | 社招 | [guide](../src/scrapers/alibaba_social/guide.md) |
| `boe` | 京东方 | JD | 社招 | [guide](../src/scrapers/boe/guide.md) |
| `huawei` | 华为 | JD | 社招 | [guide](../src/scrapers/huawei/guide.md) |
| `sany` | 三一集团 | JD | 社招 | [guide](../src/scrapers/sany/guide.md) |
| `crrc` | 中国中车 | JD | 社招 | [guide](../src/scrapers/crrc/guide.md) |
| `zhonglian` | 中联重科 | JD | 社招 | [guide](../src/scrapers/zhonglian/guide.md) |
| `inovance` | 汇川技术 | JD | 社招 | [guide](../src/scrapers/inovance/guide.md) |
| `tebian` | 特变电工 | JD | 社招 | [guide](../src/scrapers/tebian/guide.md) |
| `sungrow` | 阳光电源 | JD | 社招 | [guide](../src/scrapers/sungrow/guide.md) |
| `dji` | 大疆 | JD | 社招 | [guide](../src/scrapers/dji/guide.md) |
| `yoozoo` | 游族网络 | JD | 社招 | [guide](../src/scrapers/yoozoo/guide.md) |
| `shengqu` | 盛趣游戏 | JD | 社招 | [guide](../src/scrapers/shengqu/guide.md) |
| `zuoyebang` | 作业帮 | JD | 社招 | [guide](../src/scrapers/zuoyebang/guide.md) |
| `giant` | 巨人网络 | JD | 社招 | [guide](../src/scrapers/giant/guide.md) |
| `mgtv` | 芒果TV | JD | 社招 | [guide](../src/scrapers/mgtv/guide.md) |
| `yuanfudao` | 猿辅导 | JD | 校招/实习 | [guide](../src/scrapers/yuanfudao/guide.md) |
| `keep` | Keep | JD | 社招 | [guide](../src/scrapers/keep/guide.md) |
| `hello` | 哈啰 | JD | 社招 | [guide](../src/scrapers/hello/guide.md) |
| `zhihu` | 知乎 | JD | 社招 | [guide](../src/scrapers/zhihu/guide.md) |
| `iqiyi` | 爱奇艺 | JD | 社招 | [guide](../src/scrapers/iqiyi/guide.md) |
| `papergames` | 叠纸游戏 | JD | 社招 | [guide](../src/scrapers/papergames/guide.md) |
| `maimai` | 脉脉 | JD | 社招 | [guide](../src/scrapers/maimai/guide.md) |
| `minimax` | MiniMax | JD | 社招 | [guide](../src/scrapers/minimax/guide.md) |
| `soul` | Soul | JD | 社招 | [guide](../src/scrapers/soul/guide.md) |
| `lilith` | 莉莉丝 | JD | 社招 | [guide](../src/scrapers/lilith/guide.md) |
| `dewu` | 得物 | JD | 社招 | [guide](../src/scrapers/dewu/guide.md) |
| `sensetime` | 商汤科技 | JD | 社招 | [guide](../src/scrapers/sensetime/guide.md) |
| `vip` | 唯品会 | JD | 社招 | [guide](../src/scrapers/vip/guide.md) |
| `nowcoder` | 牛客网 | 面经 | — | [guide](../src/scrapers/nowcoder/guide.md) |
| `github` | GitHub 经验帖 | 成功经验/面经（issue 帖） | — | [guide](../src/scrapers/github/guide.md) |

> `get_scraper_guide(company)` 运行时读取同一份 guide.md。新增企业时在包内附
> guide.md 即自动生效（模板见 `_template/guide.md`）。
>
> 飞书招聘源（`papergames` / `maimai` / `minimax` / `soul` / `lilith` / `dewu` /
> `sensetime`）依赖 Playwright Chromium，首次使用需执行
> `playwright install chromium`。

企业档位（大厂 / 中厂 / 小厂）、行业与别名由 `src/scrapers/companies.yaml` 维护；
`list_data_sources` 会显示每个源的档位与行业。目录也收录暂未接入 scraper 的企业，
用于「目标企业筛选」阶段，未接入的企业会标注为需手动投递。

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
| 经验帖（experiences） | 同背景成功路径（学历/届别自述） | 案例搜寻（search_cases）、方向可行性佐证 |
| 薪资 | 了解市场行情 | 目标设定、期望管理（并非所有源公开） |

## 参考实现

新增腾讯/百度/阿里 scraper 时参考了以下开源项目（代码注释中保留具体出处）：

- [HA7CH/job-pro](https://github.com/HA7CH/job-pro)：腾讯校招接口、阿里 batch/CSRF 流程
- [Enzoding/JobHunt-CLI](https://github.com/Enzoding/JobHunt-CLI)：多站点统一字段与渠道映射
- [Nanaeo/RecruitSpider](https://github.com/Nanaeo/RecruitSpider)：腾讯/百度早期实现
- [devnp2007/career-ops](https://github.com/devnp2007/career-ops)：美团 getJobList 接口与字段映射
- [CSDN：网易招聘 queryPage 接口](https://blog.csdn.net/weixin_65149153/article/details/140274834)：网易列表接口参数

## 贡献新 Scraper

1. 复制模板：`cp -r src/scrapers/_template src/scrapers/{company}`
2. 实现 `search()` / `get_detail()`，声明 `PARAMS`
3. 填写包内 `guide.md`（缺文件会挂测试）
4. 在 `src/scrapers/config.yaml` 注册
5. 提交 PR

详见 [CONTRIBUTING.md](../CONTRIBUTING.md)。
