# BOSS直聘 使用指南

## 用途

搜索 BOSS直聘（zhipin.com）的真实岗位数据，含明确的**明文薪资**。抓取通过
Chrome DevTools Protocol（CDP）复用本地专用浏览器的真实登录态，旁听页面自身
发出的搜索接口，不注入 XHR。

BOSS 是补充源：
- 研究阶段默认 **list-only**：保留薪资、公司、地点、技能/标签与福利，不逐条补 JD。
- 需要全文时再用 `fetch_jd_detail(url)` 交互式补抓单条详情。

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| keyword | 是 | 搜索关键词，如 `"Python"`、`"AI Agent"` |
| city | 否 | 城市名（`"北京"`、`"上海"`、`"全国"`）或 9 位城市代码 |
| limit | 否 | 返回数量上限，默认 20 |

`experience` / `degree` / `salary` 暂不支持：BOSS 搜索接口需要经过校验的筛选码，
本源未实现可靠映射。传入这些参数会返回明确的「不支持」错误，不会被静默忽略。

## 调用示例

```
fetch_company_jobs(company="boss", params='{"keyword":"AI Agent", "city":"上海", "limit":10}')
fetch_jd_detail(url="https://www.zhipin.com/job_detail/xxx.html")
```

## 返回字段（列表）

| 字段 | 说明 |
|------|------|
| title | 岗位名称 |
| company | 公司名称 |
| location | 工作地点 |
| salary | 明文薪资（接口 `salaryDesc`） |
| summary | skills / job_labels / welfare 拼接摘要 |
| url | 详情页链接（可传给 fetch_jd_detail） |
| skills / job_labels / welfare | 技能、岗位标签、福利 |
| boss_active_status | 招聘者活跃状态（如「在线」） |
| detail_status | 列表阶段固定为 `list_only` |

`fetch_jd_detail` 返回 `description`（JD 全文）、`skills`、`boss_active_status`，
`detail_status="ok"`；失败返回 `{"error": ...}`。

## 首次设置与登录

1. 确保已安装 **Google Chrome 或 Microsoft Edge**（工具不回退 Chromium）。
2. 用户同意抓取 BOSS 后，Agent 先调用 `boss_login(action="status")`；未就绪时
   直接调用 `boss_login(action="login")`：

   ```
   boss_login(action="login")
   ```

   工具会启动 **Career Kit 专用浏览器**，打开可见登录页
   `https://www.zhipin.com/web/user/?ka=header-login`，用户只需扫码。
   探测使用独立的后台标签页，不会导航或复用户可见的登录页。
   只有接口返回明文薪资才算登录成功，随后写入登录标记（6 小时有效）。
3. 登录只打开**一个专用窗口**：流程会清理浏览器恢复会话时带出的旧标签页并激活
   唯一登录页，不会再出现多个扫码页。登录成功后该窗口会切到「登录成功」提示页，
   不会停在登录页；窗口**保持常驻**，后续抓取复用，不需要反复唤起登录。
   需要关闭时调用 `boss_login(action="close")`。
4. 专用 profile：`~/.career-kit/cache/boss/cdp-profile`。
   不会读取或写入 `~/.boss-zhipin-scraper`，也不会抢用户主浏览器。
5. CDP 端口默认 `9222`，可用环境变量 `CAREER_KIT_BOSS_CDP_PORT` 覆盖。
6. 调研抓取时若专用浏览器未启动，会**自动拉起**同一 profile；
   抓取只使用后台标签页，不操作用户可见页。

## 错误处理

| 错误 | 原因 | 解决 |
|------|------|------|
| `需要登录 BOSS 直聘` | 登录标记不存在、超过 6 小时或 CDP 后端不可用 | 调用 `boss_login(action="login")` 扫码 |
| `未检测到可用登录态` | 浏览器未登录 / 登录态失效 | `boss_login(action="login")` 后重试 |
| `BOSS 接口返回限制状态` | 风控/验证/访问频繁 | 先在浏览器完成验证，稍后再试；关闭代理/VPN |
| `未捕获到 BOSS 搜索响应` | 页面未加载、未登录或风控 | 确认专用浏览器能打开搜索页；稍后重试 |
| `未检测到 Chrome 或 Edge` | 未安装受支持浏览器 | 安装 Chrome/Edge，不要用 Chromium |
| `无法连接 CDP 端口` | 端口被占用或浏览器未启动 | 换 `CAREER_KIT_BOSS_CDP_PORT`，或重新登录 |
| `详情页被登录墙截断` | 详情需要有效登录态 | `boss_login(action="login")` 后再 fetch_jd_detail |
| `不支持参数：experience/degree/salary` | 本源未实现这些筛选 | 移除参数；只传 keyword / city / limit |

## 注意事项

1. **一次同意**：抓取前只问一次是否把 BOSS 纳入本次调研；同意后未登录时直接
   调用 `boss_login(action="login")`，不再追问第二次。错误码按入口区分：
   `gather_research_data` 未登录返回 `ACTION_REQUIRED`；
   `collect_company_evidence` / `fetch_company_jobs` / `fetch_jd_detail`
   未登录返回 `LOGIN_REQUIRED`；两者都带 `next_tool=boss_login`。
   不得静默跳过该源或直接宣布失败。
2. **登录态不伪装**：只有接口返回明文薪资才写登录标记；未登录/风控明确失败，
   不保存注定失效的状态。登录成功后浏览器窗口保持常开，由
   `boss_login(action="close")` 关闭。
3. **研究阶段 list-only**：BOSS 行不补详情、不剔除；数据缺口会写明
   「BOSS 仅列表数据，未抓 JD 详情」，需要全文时用 `fetch_jd_detail` 补抓。
4. 抓取频率受风控限制，短时间多次调用可能被临时限制。

## 开源归属

CDP 接入的核心思路参考并裁剪自
[eatmoreduck/boss-zhipin-scraper](https://github.com/eatmoreduck/boss-zhipin-scraper)
（MIT，Copyright (c) 2026 eatmoreduck）。详见同目录 `THIRD_PARTY_NOTICES.md`。
