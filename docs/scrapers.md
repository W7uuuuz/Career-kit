# 企业数据源

> Career Kit 已收录的企业数据源。单一事实源：
> - 注册 = `src/scrapers/config.yaml`
> - 企业元数据与别名 = `src/scrapers/companies.yaml`（统一查询入口 `loader.resolve_company`；`catalog.get_company` 只覆盖企业名）
> - 参数 = 各源 `scraper.py` 的 `PARAMS`
> - 教程 = 各源包内的 `guide.md`
>
> 本文档只做索引与链接，不复制通用参数表。
>
> 当前注册 59 个数据源（55 个企业招聘源 + BOSS 直聘 + 牛客 + GitHub + 实习僧），
> 企业目录收录 90 家，其中 54 家可自动抓取。

## 已收录企业

| ID | 名称 | 数据类型 | 支持渠道 | 使用教程 |
|----|------|----------|----------|----------|
| `boss` | BOSS直聘 | JD（含 CDP 明文薪资） | 社招 | [guide](../src/scrapers/boss/guide.md) |
| `bytedance` | 字节跳动 | JD | 社招 / 校招 | [guide](../src/scrapers/bytedance/guide.md) |
| `tencent` | 腾讯 | JD | 社招 / 校招 / 实习 | [guide](../src/scrapers/tencent/guide.md) |
| `baidu` | 百度 | JD | 社招 / 校招 / 实习 | [guide](../src/scrapers/baidu/guide.md) |
| `alibaba` | 阿里巴巴 | JD | 校招 / 实习（社招见 `alibaba_social`） | [guide](../src/scrapers/alibaba/guide.md) |
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
| `alibaba_social` | 阿里巴巴（社招） | JD | 社招（校招/实习见 `alibaba`） | [guide](../src/scrapers/alibaba_social/guide.md) |
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
| `sanqi` | 三七互娱 | JD | 社招 | [guide](../src/scrapers/sanqi/guide.md) |
| `tal` | 好未来 | JD | 校招/实习 | [guide](../src/scrapers/tal/guide.md) |
| `mihoyo` | 米哈游 | JD | 社招 | [guide](../src/scrapers/mihoyo/guide.md) |
| `tongcheng` | 同程旅行 | JD | 社招 | [guide](../src/scrapers/tongcheng/guide.md) |
| `youzan` | 有赞 | JD | 社招 | [guide](../src/scrapers/youzan/guide.md) |
| `megvii` | 旷视科技 | JD | 社招 | [guide](../src/scrapers/megvii/guide.md) |
| `shein` | SHEIN | JD（不公开薪资） | 社招 / 校招 / 实习 | [guide](../src/scrapers/shein/guide.md) |
| `shopee` | Shopee | JD | 社招 | [guide](../src/scrapers/shopee/guide.md) |
| `oppo` | OPPO | JD（不公开薪资） | 校招 / 国际化 / 博士项目 | [guide](../src/scrapers/oppo/guide.md) |
| `vivo` | vivo | JD | 社招 | [guide](../src/scrapers/vivo/guide.md) |
| `douban` | 豆瓣 | JD | 社招/校招/实习 | [guide](../src/scrapers/douban/guide.md) |
| `momo` | 陌陌 | JD | 社招 | [guide](../src/scrapers/momo/guide.md) |
| `nowcoder` | 牛客网 | 面经 | — | [guide](../src/scrapers/nowcoder/guide.md) |
| `github` | GitHub 经验帖 | 成功经验/面经（issue 帖） | — | [guide](../src/scrapers/github/guide.md) |
| `shixiseng` | 实习僧 | JD（近一月实习） | 实习 | [guide](../src/scrapers/shixiseng/guide.md) |

> `get_scraper_guide(company)` 运行时读取同一份 guide.md。新增企业时在包内附
> guide.md 即自动生效（模板见 `_template/guide.md`）。
>
> 飞书招聘源（`papergames` / `maimai` / `minimax` / `soul` / `lilith` / `dewu` /
> `sensetime`）通过页面前端签名捕获接口响应，优先使用系统默认 Chrome / Edge；
> 未检测到 Chrome / Edge 时回退 Playwright Chromium，需执行
> `playwright install chromium`。
>
> BOSS 直聘通过 CDP 连接本地已登录的 Chrome / Edge，旁听页面自身的搜索接口，
> 返回**明文薪资**；不注入 XHR、不回退 Chromium。登录用
> `boss_login(action="login")`：用户只扫码，登录成功后专用浏览器窗口保持常驻，
> 后续抓取自动复用；需要关闭时用 `boss_login(action="close")`。专用 profile：
> `~/.career-kit/cache/boss/cdp-profile`，CDP 端口默认 9222，可用
> `CAREER_KIT_BOSS_CDP_PORT` 覆盖。登录态有效期 6 小时（唯一来源
> `LOGIN_TTL_SECONDS`）。研究阶段 BOSS 默认 **list-only**：保留薪资、
> 公司、地点、技能标签与福利，不逐条补 JD；需要全文时用 `fetch_jd_detail(url)`
> 交互式补抓。失败原因会如实写入报告来源状态与数据缺口。
>
> 实习僧（`shixiseng`）匿名解析公开 SSR 页面，只收录近一月刷新的实习岗位；
> 列表页不逐条补详情，需要 JD 全文时用 `fetch_jd_detail(url)`。站点用 iconfont
> 私有区字符渲染部分汉字与数字，scraper 只剥离不解析，残缺薪资如实留空。

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

## 数据用途

| 数据类型 | 用途 | 使用场景 |
|----------|------|----------|
| JD | 了解岗位要求 | 差距分析、路线图规划 |
| 面经 | 了解面试内容 | 面试准备、技能补充 |
| 经验帖（experiences） | 同背景成功路径（学历/届别自述） | 案例搜寻（search_cases）、方向可行性佐证 |
| 薪资 | 了解市场行情 | 目标设定、期望管理（并非所有源公开） |

## 薪资渠道说明

调研报告的薪资只取各数据源在抓取结果里真实返回的字段，代码不做估算、补全或跨源推断。
报告会单独列出「多少条含薪、来自哪个源」，没有薪资时数据缺口会写明原因和可选动作。

### 当前可用来源

| 渠道 | 薪资形态 | 是否需登录 | 抓取风险 | 状态 |
|------|----------|------------|----------|------|
| BOSS 直聘（`boss`） | 列表明文薪资（`salaryDesc`，如 `25-45K·16薪`） | 需扫码登录（`boss_login`，登录态 6 小时，窗口常驻复用） | 中高：风控、环境异常、登录态失效 | 已接入，当前主要含薪来源 |
| 企业官网 / ATS（其余已注册源） | 多数不公开；少数岗位在接口字段里带薪资（如北森 `Salary`、同程 `salaryRange`、有赞 `salaryText`、飞书 `min_salary/max_salary`、Moka/大易个别字段） | 否 | 低至中 | 已接入；有值就保留，无值如实留空 |

说明：

- 官网未返回薪资时，报告只写「未获取」，不把它当作「岗位无薪资」，也不用行业均值补位。
- BOSS 研究阶段默认 list-only：保留薪资、公司、地点、技能标签，不逐条补 JD；需要全文时用 `fetch_jd_detail(url)`。
- BOSS 未选择、未登录或抓取失败时，薪资缺口无法由其他已注册源补齐；报告会如实写明。

### 未接入的薪资渠道（评估结论）

以下渠道未接入。原因是拿不到合法、稳定、可核验的公开薪资数据；此处只记录评估结论，
不提供未经验证的接口。

| 渠道 | 是否公开薪资 | 是否需登录 | 抓取风险 | 结论 |
|------|--------------|------------|----------|------|
| 看准网 | 以公司点评与薪资爆料为主，不是结构化岗位薪资 | 通常需要登录，且与 BOSS 同体系风控 | 高：登录墙、验证、页面结构频繁变化 | 未接入 |
| 职友集 | 部分公司薪资页可公开访问，但多为聚合/二手数据 | 部分页面不需要，高频访问会触发反爬 | 中高：数据时效与来源难核验、反爬 | 未接入 |
| OfferShow | 校招 offer 爆料（UGC），不是企业官方 JD 薪资 | 以小程序/授权为主 | 高：授权限制、数据非官方、难以稳定抓取 | 未接入 |
| 脉脉 | 职言/薪资爆料非结构化；仓库内 `maimai` 源只是飞书招聘的岗位 JD | 职言需登录 | 高：登录风控强、内容非结构化 | 未接入（现有 `maimai` 源不含薪资） |

若后续考虑接入新渠道，需要同时满足：

1. 数据公开可核验，且使用方式符合站点条款与当地法规；
2. 不绕过登录、验证码或风控；
3. 有明确限频与失败降级，单源失败如实写入来源状态，不影响其他源；
4. 只保存来源原始薪资文本，不做估算，也不跨源合并推断。

在满足上述条件前，报告只承诺「BOSS 直聘」与「已注册企业源可能返回的薪资」，
并给出三种动作：补充 BOSS、导入含薪 JD、接受缺口。

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
5. 在 `src/scrapers/companies.yaml` 补充企业名称、档位、行业、别名与 scraper 映射
6. 在本文档补充数据源条目
7. 提交 PR

详见 [CONTRIBUTING.md](../CONTRIBUTING.md)。
