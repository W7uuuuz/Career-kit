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
| experience | 否 | 经验要求，如 `"1-3年"`、`"3-5年"`、`"不限"` |
| degree | 否 | 学历要求，如 `"本科"`、`"硕士"`、`"不限"` |
| salary | 否 | 薪资范围，如 `"15-25K"`、`"30-50K"` |
| limit | 否 | 返回数量上限，默认 20 |

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
2. 运行登录命令（**优先由 Agent 的 harness 直接执行**，用户只需扫码）：

   ```
   "<venv-python>" -m src.scrapers.boss.login
   ```

   工具会启动 **Career Kit 专用浏览器**，打开
   `https://www.zhipin.com/web/user/?ka=header-login`，等待扫码；会复用浏览器启动时
   的默认标签页，若仍看到默认新标签页请忽略它，直接在登录页扫码。确认接口能返回
   明文薪资后写入登录标记（6 小时有效），并**自动关闭专用浏览器**。

3. 专用 profile：`~/.career-kit/cache/boss/cdp-profile`。
   不会读取或写入 `~/.boss-zhipin-scraper`，也不会抢用户主浏览器。
4. CDP 端口默认 `9222`，可用环境变量 `CAREER_KIT_BOSS_CDP_PORT` 覆盖。
5. 调研抓取时若专用浏览器未启动，会**自动拉起**同一 profile。

## 错误处理

| 错误 | 原因 | 解决 |
|------|------|------|
| `需要登录 BOSS 直聘` | 登录标记不存在、超过 6 小时或 CDP 后端不可用 | 重新运行登录命令扫码 |
| `未检测到可用登录态` | 浏览器未登录 / 登录态失效 | 扫码登录后重试 |
| `BOSS 接口返回限制状态` | 风控/验证/访问频繁 | 先在浏览器完成验证，稍后再试；关闭代理/VPN |
| `未捕获到 BOSS 搜索响应` | 页面未加载、未登录或风控 | 确认专用浏览器能打开搜索页；稍后重试 |
| `未检测到 Chrome 或 Edge` | 未安装受支持浏览器 | 安装 Chrome/Edge，不要用 Chromium |
| `无法连接 CDP 端口` | 端口被占用或浏览器未启动 | 换 `CAREER_KIT_BOSS_CDP_PORT`，或重新运行登录命令 |
| `详情页被登录墙截断` | 详情需要有效登录态 | 重新扫码登录后再 fetch_jd_detail |

## 注意事项

1. **交互纪律**：抓取前先问用户是否抓取 BOSS；未登录/登录过期时返回
   `LOGIN_REQUIRED` / `CONFIRMATION_REQUIRED`。询问时说明「我可以帮你打开登录窗口，
   你只需扫码」；用户同意后 Agent 用 harness 的终端/Bash 运行 `login_command`，
   不要把命令丢给用户手动执行，也不得静默跳过该源或直接宣布失败。
2. **登录态不伪装**：只有接口返回明文薪资才写登录标记；未登录/风控明确失败，
   不保存注定失效的状态。
3. **研究阶段 list-only**：BOSS 行不补详情、不剔除；数据缺口会写明
   「BOSS 仅列表数据，未抓 JD 详情」，需要全文时用 `fetch_jd_detail` 补抓。
4. `salary` 过滤为**近似过滤**：BOSS API 对日薪岗（如「250-400元/天」）不生效，
   结果中可能混入日薪岗位。
5. 抓取频率受风控限制，短时间多次调用可能被临时限制。

## 开源归属

CDP 接入的核心思路参考并裁剪自
[eatmoreduck/boss-zhipin-scraper](https://github.com/eatmoreduck/boss-zhipin-scraper)
（MIT，Copyright (c) 2026 eatmoreduck）。详见同目录 `THIRD_PARTY_NOTICES.md`。
