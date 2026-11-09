# Changelog

## Unreleased

- **设计一致性修复（2026-11-09）**：
  - 建档首轮合并为「简历或 4 项采集卡」，事实可一次采集，用户亲口陈述即确认；
    `finalize_profile` 不再代替用户确认目标。
  - 下一步统一由 `resolve_progress` 派生；企业适配改为执行前必做；
    `gap_stale_at` 强制回到差距分析。
  - BOSS 直聘新增 `boss_login(status/login/close)`：登录页/探测页/抓取页隔离，
    登录窗口唯一、成功后切到登录成功页，浏览器常驻复用；TTL 统一 6 小时；
    `experience/degree/salary` 显式不支持。
  - 数据源别名统一走 `companies.yaml`/loader；Nowcoder `order`、
    Baidu/Tencent `limit`、GitHub `filter_company` 生效；详情字段、数据源计数与
    SHEIN/OPPO 描述对齐。
  - Artifact 阶段 2-10 强制上游引用；ExecutionState 只在 applied plan 后落库；
    新计划强制重新生成任务；`evidence_ids` 校验单源；需求统计拒绝草稿数字；
    证据阶段尊重 BOSS list-only。
  - 工具数 49 → 50。

## v0.3.0 (2026-11-09)

- **0.3 发布补充（2026-11-09）**：
  - **Core v2 12 阶段工作流**：档案、目标、市场、差距、基线、企业池、证据、需求、执行版、执行、投递、复盘；artifact 状态机与 sync 层贯通。
  - **企业适配**：目标企业筛选、JD/面经证据池、需求统计（频率/公司覆盖/Wilson 区间）、执行方案校准与计划失配检测。
  - **P0 体验**：开屏改为定位/规划/执行三段；去掉市场调研等不必要确认；选项加推荐；阶段类型中文化。
  - **P1/P2**：简历自我介绍式摸排、最终结果预期、路线图 3-6 段、毕业届/占位 JD 提示、第 10/11 步维护化与结束语、资产中心规划链路。
  - **控制台升级**：从 http.server + vanilla JS 升级为 FastAPI + Vue 3 + Vite + TypeScript；保留 token 鉴权、SSE、任务编辑、投递登记、职业地图与资产入口。
  - **BOSS 直聘**：改为 CDP 复用本地已登录 Chrome/Edge，旁听页面自身搜索接口获取明文薪资；研究阶段 list-only，详情交互式补抓；登录态 6 小时有效。
  - **同步状态**：740+ 单测、E2E core、doctor、wheel 构建与真实 BOSS 搜索/详情验证通过。

- **数据源扩容**：接入 18 家互联网企业（Moka / 北森 / 飞书）与唯品会独立 Moka 源，
  注册数据源 27 → 46；企业目录收录 64 家（42 家可自动抓取），`docs/scrapers.md` 同步。
- **飞书源浏览器策略**：优先使用系统默认 Chrome / Edge，未检测到时回退 Playwright Chromium。
- **Core v2 企业适配第一纵切（2026-11-08）**：
  - 新增企业目录 `src/scrapers/companies.yaml` 与档位标签（大厂/中厂/小厂），
    `list_data_sources` 显示档位与行业；先覆盖互联网，制造/能源企业只打标不进入默认适配。
  - 新增 6 个企业适配工具：`select_target_companies`、`collect_company_evidence`、
    `analyze_company_requirements`、`save_requirement_profile`、
    `plan_execution_alignment`、`save_execution_alignment`（工具数 41 → 49）。
  - 证据层：批量抓取目标企业 JD + 面经，城市硬筛、详情补抓、去重、来源状态与样本置信度；
    报告落盘 `~/CareerKit/<档案>/证据池/`。
  - 需求分析：频率、公司覆盖、Wilson 95% 区间与逐条硬门槛由代码计算；
    LLM 只能写 `interpretation`，保存时重算并校验，不能再自评数字。
  - 执行方案校准：预览/确认门禁；每条变更必须带 `evidence_ids`；已完成任务保留、
    旧 pending/in_progress 不迁移；维护 `plan_history`、`adjustments` 与 `core_state`。
  - 用户流程新增「企业适配」阶段（阶段 6-9）；`get_workflow_status` 与 `save_roadmap`
    给出企业适配的下一步提示。
  - 新增 `check_plan_fit`：证据刷新 / 里程碑 / 周检视后检测计划失配，
    返回给用户的询问话术；不自动改计划。`get_workflow_status` 与周检视已接入。
  - 执行版下游打通：`generate_tasks` 能区分历史任务与新执行版阶段，
    保留 completed/skipped、清理旧 pending；职业地图、进度、控制台可展示执行版与证据摘要。
  - 旧档案兼容：旧 `plan/tasks/research` 可直接读取；首次使用自动建 artifacts 表；
    应用执行版可保留完成历史、清理未完成任务。
  - 本地控制台新增「企业适配」卡片：阶段、企业池、证据条数与置信度、需求画像、
    执行版状态与报告链接。
  - 新增测试：Core artifact 基座、阶段 6-9、企业适配全链路、执行版下游、
    旧档案兼容、计划失配检测、控制台状态。
  - **12 阶段新流程**：用户可见流程统一为 12 步（职业档案构建 → 目标岗位定位 →
    市场基线调研 → 能力差距诊断 → 培养方案规划 → 目标企业筛选 → 岗位与面经采集 →
    企业需求分析 → 执行方案校准 → 任务执行与打卡 → 求职投递管理 → 周期复盘与计划调整）。
  - 新增 sync 层，把阶段 1-5、10-12 的既有档案数据写入新 artifact 与 `core_state`；
    state_machine、guidance、`get_workflow_status` 统一按 12 阶段推进；阶段 11/12 为可选/周期阶段。
  - **BUG 修复（真实 E2E 记录）**：
    - `check_plan_fit` 增加技能别名与泛化软技能降级，修复执行版刚应用后误报 `major_drift`；
    - `gather_research_data` 单源 25 秒 / 总预算 50 秒，源较多时提示拆批；
    - doctor 新增包版本检查，暴露 editable 元数据陈旧；
    - `collect_company_evidence` 新增 `fresh_jobs`，文案区分「新抓 / 复用 / 保留」；
    - `record_application` / `delete_application` 同步更新投递清单候选状态（applied / pending）；
    - 阶段 7 引导增加「补充 BOSS 薪资后采集」选项。
  - 版本：`0.2.3` → `0.3.0`；工具数 41 → 49。

## v0.2.3 (2026-11-07)

- **数据源扩容到 27 个**：新增美团 / 网易 / 京东 / 快手 / 拼多多 / 小红书 /
  滴滴 / 蚂蚁 / 携程 / B站 / 小米 / 阿里社招，以及京东方 / 华为 / 三一 / 中车 /
  中联 / 汇川 / 特变 / 阳光电源等制造 / 能源 / 硬件企业。
- **行业包**：新增电子 / 机械 / 电气行业包与数据适配，支持互联网之外的方向。
- **在线演示改版**：对话式体验页、选择驱动流程、同背景案例与面经卡片、
  差距面板与实时职业地图渲染。
- **分发包优化**：wheel 不再打包演示 GIF / png / 演示页与构建脚本
  （仅保留 `career-kit-demo` 需要的自包含 `chat-demo.html`，体积从约 5.1MB
  回落到 0.5MB 内）；sdist 排除 `.github` / `.claude` / `.opencode` 等开发资产。
- **PyPI README**：示例图片与文档链接改为绝对地址，修复 PyPI 页面图片与
  链接 404。
- **安装稳定性**：锁定 `iv8==0.1.4`（仅官方 PyPI 提供，国内镜像常缺失）。
- **doctor**：正确读取 `mcp` 包版本号，避免显示 `unknown`。

## v0.2.2 (2026-11-05)

- **MCP Registry**：namespace 大小写改为 `io.github.W7uuuuz/career-kit`，与
  GitHub OIDC 授权（`io.github.W7uuuuz/*`）一致；PyPI README 的 `mcp-name`
  标记同步更新。

## v0.2.1 (2026-11-05)

- **MCP Registry**：README 增加 `mcp-name: io.github.w7uuuuz/career-kit`
  所有权标记；`server.json` 描述压缩到 100 字符以内，满足官方 Registry 的
  PyPI 包校验。
- **文档**：补充 `uvx` 镜像回退（`--default-index https://pypi.org/simple`）
  与常见问题。

## v0.2.0 (2026-11-04)

首个面向公开发布的版本，重点是把「装得上、看得懂、点得动」补齐。

- **一行安装**：补齐 PyPI 元数据（classifiers / keywords / project.urls），新增
  `publish.yml`（Trusted Publishing，推送 `v*` tag 自动发布），安装可简化为
  `uvx --from career-kit career-kit`。
- **官方 MCP Registry**：新增 `server.json`（pypi / uvx / stdio），可直接发布到
  registry.modelcontextprotocol.io。
- **在线演示**：新增 `docs/index.html` 与 `pages.yml`，把 `docs/examples/demo/`
  的交互式职业地图部署到 GitHub Pages，README 首屏提供零安装体验入口。
- **零安装本地演示**：新增 `career-kit-demo` 命令，打开随包附带的职业地图。
- **首屏与国际化**：README 重写为「一句话 + 在线体验 + 一行安装 + 60 秒 demo」；
  新增 `README.en.md` 与中英文切换。
- **开源协作**：新增 `DISCLAIMER.md`、`CODE_OF_CONDUCT.md`、issue 表单
  （bug / feature）与 Discussions 入口。
- **隐私**：演示数据全部匿名化（示例用户 / 一线城市 / 面议）；GitHub Pages
  只发布落地页与演示 HTML，不上传任何原始档案 JSON。
- **版本**：`0.1.0` → `0.2.0`。

## Unreleased

- **2026-11-04 复测清单修复（P0/P1/P2）**：
  - 调研抓取：单源 30 秒 / 总预算 75 秒，超时不拖垮整批；已完成来源写断点缓存，
    重跑自动续抓；案例计数统一为「最终进入花名册的条数」
  - BOSS：抓取前先做登录预检，未登录直接返回 `LOGIN_REQUIRED`，不浪费整批；
    岗位公司名缺失时标「公司名未获取」；登录脚本统一 UTF-8 输出
  - 流程：`finalize_profile` 下一步改为先调研；GUIDE 不再重复分析前的问题；
    `get_workflow_status` 从实际报告推导已完成步骤；工作目录不一致显式告警
  - 路线图/任务：只生成当前阶段任务，避免后续阶段空壳；`generate_tasks` 后自动刷新
    职业地图 HTML；审计过期改为提示重新审计；质量建议去除重复里程碑名与
    `evidence_gate`/`condition` 假阳性
  - 报告命名统一为 `日期_时分_方向`；离线职业地图补充「下载打卡 JSON」并明确
    localStorage 丢失风险

- **SQLite 存储 + 控制台写操作 + 静态地图薄客户端（2026-11-03）**：
  - 档案主存储迁移到 `~/.career-kit/career-kit.db`（SQLite，WAL）；
    JSON 保留为兼容镜像，旧 JSON 自动导入，E2E/手工查看不受影响
  - 控制台新增任务编辑（名称/描述/how_to/完成标准/打卡方式）、投递登记、
    调研报告列表与方向筛选；SSE 自动刷新
  - 静态职业地图新增薄客户端模式：由控制台 `/roadmap` 提供时打卡直接走 API，
    `file://` 打开时回退 localStorage，并显示当前模式提示
  - `/api/asset` 与 `/api/events` 受 token 保护；资产访问限制在 `~/CareerKit`
  - 新增 `tests/test_profile_sqlite.py`；Web 测试覆盖任务编辑、投递登记、
    报告列表与 `/roadmap`
  - 文档收敛：`docs/workflow.md` 为唯一流程源；`docs/llms.txt` 改为命令速查，
    `session.py` 改为执行纪律手册，不再复制完整流程

- **当前阶段与进度口径统一（2026-11-03）**：
  - 新增 `task_manager.resolve_current_phase()`：唯一当前阶段判定（跳过零任务阶段、
    `skipped` 算完成、全部完成返回 None、无任务返回第一段）
  - `current_phase_view`、`detail_current_phase`、职业地图、进度仪表盘、本地控制台
    全部改用同一判定，避免不同入口高亮不同阶段
  - 全部完成时不再打 `[当前]`，页面显示「全部完成」并保留一张可见卡片
  - 新增 `save_current_detail` 的 checkin_mode/goal 校验建议（无效 mode、daily goal<1、
    percent goal 越界），避免任务永远无法完成
  - 目标复述兼容 `direction/position/industry` 等键；match_score 统一为三维口径

- **全仓审计后的数据一致性修复（2026-11-03）**：
  - 打卡协议统一：percent 的 amount 为绝对目标值；daily 同日幂等，amount>1 为目标天数；
    静态地图 daily 进度不再归零，percent 不再把绝对值当增量累加
  - 任务身份稳定：`generate_tasks` 按「阶段 + 里程碑 + 任务名」复用旧 ID 与打卡进度，
    不再每次从 `task_001` 重排；能力证据只在任务真正完成时写入并按完成时间去重
  - `save_roadmap` 保留未变更阶段的 `current_detail`，路线图 hash 只算 roadmap 内容；
    重复保存不再清空 `audited_phases`
  - 控制台撤销删除最近一条打卡与能力证据；`/api/asset` 受 token 保护且限制在资产根内
  - 修复 `--open` 参数缺失（桌面快捷方式可直接启动）；资源筛选按阶段专属标签优先，
    实习阶段的 BOSS/牛客不再被截断
  - 文档：根 `llms.txt` 执行顺序改为先细化；工具数副本、MCP Resources、
    README BOSS 登录与隐私路径同步；wheel 纳入 `sop/` 与 `docs/`（排除 internal）
  - 新增/更新测试：稳定 ID、同日幂等、detail 保留、资源优先级、asset 路由、CLI `--open`

- **档案写入安全打磨（2026-11-03）**：
  - 新增 `profile_lock`：Windows msvcrt / POSIX fcntl 跨进程写锁，同线程可重入
  - `save_profile` 改为临时文件 + `os.replace` 原子替换，避免 MCP 与 Web
    同时读写时读到半截 JSON
  - 写入临界区（`merge_section` / `save_plan_snapshot` / 删除/恢复 / Web 打卡）
    统一加锁；新增 `tests/test_profile_lock.py`（并发写后文件仍合法）

- **本地控制台 + 桌面快捷方式（2026-11-03，P2+P3 MVP）**：
  - 新增 `src/web.py`：`career-kit-serve` 启动本地 HTTP 控制台，只绑定 `127.0.0.1`，
    启动 token 鉴权；前端不使用 localStorage，打卡直接写回档案
  - 新增 `src/web_ui/`：路线图查看、任务怎么做/资源/完成标准、once/daily/percent
    打卡与撤销；MCP 下次运行直接读到同一份进度
  - 控制台补充：任务未生成时展示里程碑预览、市场调研摘要与来源链接、
    最近投递记录；失败源在控制台直接可见
  - `install.ps1` / `install.sh` 增加桌面快捷方式（Windows `.lnk`、macOS/Linux `.command`）
  - 职业地图增加单任务撤销与里程碑完成数
  - 新增 `tests/test_web.py`；`pyproject.toml` 注册 `career-kit-serve`

- **引导与执行 playbook（2026-11-03，P0+P1）**：
  - `[USER_BRIEF]` 增加「这是什么 / 能帮你做什么 / 怎么用 / 数据在本机」四段，
    新用户第一轮就知道产品边界与预期
  - `[GUIDE]` 增加「本轮要做什么 / 怎么做 / 结果怎么读」；差距分析与起点判定
    在给分数前先播报口径（维度、权重、档位含义），规则入口指向
    `career-kit://docs/rules`
  - 新增 `docs/rules.md` 与 MCP Resource：小/中/大厂定义、match_score 口径、
    起点/目标/实际投递区别、打卡方式、数据边界
  - 任务模型新增 `how_to` / `resources` / `done_criteria`；`detail_current_phase`
    要求任务带执行 playbook，并返回 `resource_catalog`
  - 新增 `sop/resources.yaml` 与 `src/tools/resource_catalog.py`：资源链接唯一来源，
    未收录时用搜索词兜底，`save_current_detail` 校验并给建议（不阻断）
  - `generate_tasks` 改为「当前阶段详细路线直接替换该阶段任务」，不再按名称弱匹配；
    修复细化任务改名后被丢弃的问题
  - 职业地图渲染任务的做法、资源链接、完成标准；任务未生成时展示里程碑预览，
    不再只剩 4 个空阶段
  - 文档与测试同步；新增 `tests/test_task_playbook.py`

- **BOSS 登录改为 Agent 直接执行（2026-11-03）**：
  - 新增 `guidance.login_action()`：统一登录交互契约，明确 `harness_can_run=true`、
    `agent_action`（用终端/Bash 直接运行登录脚本）、`user_instruction`（用户只需扫码）
  - `fetch_company_jobs` / `gather_research_data` 的 `LOGIN_REQUIRED` /
    `CONFIRMATION_REQUIRED` 询问改为「我可以直接帮你打开登录窗口扫码」；
    用户同意后由 Agent 运行 `login_command`，不再把命令丢给用户手动执行
  - BOSS guide、session 手册、workflow、llms 与命令剧本同步该纪律

- **重构引导词系统（2026-11-03）**：
  - 新增 `src/guidance.py`：6 步旅程、位置推导、本轮唯一决策、警告与文案渲染的唯一事实源；
    引导状态由档案推导（`profile.guidance`），不再依赖模型记忆
  - 用户文案与执行指令分离：`start_session` / `get_workflow_status` / `intake` / `parse_resume`
    / `save_gap_analysis` / `save_roadmap` / `generate_tasks` 直接下发 `[USER_BRIEF]` / `[GUIDE]`，
    模型只负责转述，不再自行拼流程概览
  - 目标确认纪律：简历推断的目标只能作为候选；`intake(want)` 带 `user_confirmed=true`
    才点亮「目标已确认」，否则 GUIDE 停在确认问句
  - 内部术语人话化：审计结论返回 `verdict_label`（通过 / 通过但有建议 / 发现硬矛盾），
    不再把 `PASS_WITH_NOTES`、`must_fix` 暴露给用户
  - 收敛重复文案：命令剧本与 `docs/prompts/onboarding.md` 改为只引用引导块；
    防漂移测试改为校验「单一事实源 + 命令剧本不复制模板」
  - 新增 `tests/test_guidance.py`；文档一致性测试同步重构

- **修复行业切换未标记旧分析过期（2026-10-27）**：
  - 抽出共享 `mark_industry_change`；`get_industry_snapshot` 切换行业时与 `intake` 一致
    设置 `gap_stale_at`，并在返回中暴露 `analysis_stale`
  - 新增回归测试：先扫互联网再扫能源，旧差距分析必须过期

- **BOSS 登录态 2 小时 TTL + 环境异常自动销毁（2026-10-27）**：
  - `state.json` 写入 `saved_at_ts`；登录态超过 2 小时自动失效并删除
  - 旧版无时间戳的登录态按过期处理，不再静默复用
  - API 返回「您的环境存在异常」或 HTTP 风控页命中时，自动销毁登录态与 stoken 缓存
  - 登录态校验移到搜索/详情缓存之前，过期状态不再吃旧缓存
  - 新增 `tests/test_boss_auth.py`；指南同步 2 小时有效期与重登说明

- **行业扫盲子流程 + 通用数据层（2026-10-27）**：
  - 第一轮先判断行业认知，再决定是否扫盲；扫盲是可选子流程，拒绝不阻塞规划
  - 行业为入口（MVP 互联网/软件、能源动力），专业降为可选个性化字段
  - 新增能源动力行业包：电力/发电、新能源/储能、热力暖通、汽车动力、
    能源管理与设备制造；含 7 个岗位卡、相关专业与麦可思基准
  - 新增 MCP Prompt/Resource：`career-onboarding` / `career-quick-scan` /
    `career-grounding`，统一扫盲流程与数据边界
  - 新增 `get_industry_snapshot`：行业地图 + 岗位卡 + 当前招聘样本/薪资 +
    相关专业 + 来源/样本数/数据缺口；BOSS 未登录只记缺口，不阻断
  - 不新增行业定制 Scraper；招聘数据复用通用源，同行业去向支持
    `~/.career-kit/industry_outcomes/<id>.json` 导入
  - 行业变更自动标记旧差距分析过期；档案记录 `industry_id/scan_consent/scan_summary`
  - 工具数 40 → 41；新增 `tests/test_industry_snapshot.py`

- **权限下放：质量判断交还 LLM，代码只守结构与事实（2026-10-27 实测修复）**：
  - 路线图 `save_roadmap` 改为「结构校验 + 质量建议」：层级跨度、KPI、届别、任务措辞
    等以 `advisories` 返回并持久化，不再拒绝保存；`force` 参数废弃；移除
    `start_level_after` 写回 `gap.start_level`（计划假设不污染现状）
  - 审计改为第二意见：新增 `PASS_WITH_NOTES`，FAIL 只用于硬矛盾，最多 3 条 must_fix，
    其余进 notes；审计记录移入 `profile.audit` 并按 `roadmap_hash` 绑定（修复
    `save_roadmap` 清空审计记录、force 一次永久绕过的问题）；审计不阻断定稿
  - 审计子 Agent（两份 harness 定义）改为读取 `sop/roadmap.yaml` 清单、先列通过项、
    不自行扩大规则；`sop/roadmap.yaml` 的清单增加 must/note 分级
  - 层级模型降级为命中率参考：跨级只提示依据，不禁止投递；修复
    `start_level_after` 同阶段自举绕过；未知层级、届别双向不一致均给建议
  - 差距分析：`skill_gaps` 非空、`source`、red_flags 字段、AI 作者身份提示
    全部改为 advisory；未知字段显式提示（不再静默丢弃）；`match_score` 仍做结构校验
  - 投递重复改为交互式：返回既有记录 + `duplicate`，用户确认后可
    `allow_duplicate=True` 新建；不再直接拒绝
  - BOSS 未登录不再阻断整轮调研：其他源照常执行，BOSS 记为来源失败并在结果中说明；
    仅当没有任何可用数据时才返回 `LOGIN_REQUIRED`
  - 数据口径修复：薪资区间同时统计下界/上界/中点（不再只取下界）；城市归一
    （上海/上海市/徐汇区）并输出主城市分布与多城市数量；学历改为「要求段提及次数」；
    案例统计暴露 raw/deduped/filtered；未知字段提示
  - `generate_roadmap` / `analyze_gaps` / `detail_current_phase` 的方法论上下文瘦身
    （去掉 data_needs 与重复审计清单），降低长会话截断风险
  - 摸排门禁（`PROBING_REQUIRED`）保持硬拒绝：这是防简历虚高的必备步骤
  - 新增 `tests/test_quality_advisories.py`；同步更新路线图/差距/投递/e2e 断言与文档

- **调研详情分层读取（花名册 + 按需全文）+ 2026-10-27 复测 5 项修复**：
  - 岗位详情必抓：`gather_research_data` 逐条补抓 `description/requirements`，
    未取得详情的岗位不纳入报告，剔除数量进入来源面板与数据缺口（不再以标题充数）
  - 上下文控制：新增 `read_research_details`（总 40 个工具）——不带 `ids` 返回
    「花名册（标识与摘要）+ 聚合摘要 + 子 Agent 委派方案」，带 `ids` 按需读取选定
    条目全文（`kind="jd"` 岗位 / `"case"` 面经与他人路径，单次上限 10 条）；
    岗位/案例全文仅落盘到报告、`profile.research` 与 JSON，不一次性注入模型上下文
  - 子 Agent 委派：子 Agent 属宿主 harness 能力（opencode task/subagent、
    Claude Code Task 等），由父 Agent 发起；新增 `research-analyst` 子 Agent 定义
    （`.opencode/agent/research-analyst.md` 与 `.claude/agents/research-analyst.md`，
    只读、无 bash），工具返回可直接使用的委派指令、按 10 条分组的 id 批次与输出契约
    （conclusions / shortlist / gaps），父 Agent 仅汇总子 Agent 的结论与重点名单
  - 新增 `src/research_digest.py`：确定性聚合统计（城市/薪资区间/高频要求/
    学历与层级信号/案例结构），供父 Agent 直接获得结论要素
  - 报告展示：取消二次截断（报告结构与 JSON 保留原文）；md 增加「岗位详情（完整 JD）」
    区；HTML 表格保留摘要预览并提供 `<details>` 展开全文；来源错误与缺口原因不再
    截断；薪资空值统一显示「未获取」
  - `explore_goals` 技能名改用 `skill_display_name` 多键名回退（修复 `None` 摘要）
  - 案例分类：标题成功信号优先（上岸/offer/拿到/入职/复盘…），避免「面试」二字
    把上岸帖误判为「面试要求」；案例意图词移除裸「面试」，过滤学习日志类条目
  - 本地知识库 JSON 卡片：按字段抽取可读摘要（公司/地点/薪资/正文），不再把原始
    JSON 当要点；本地 JD 与本次 JD 表按 URL/标题去重，避免「同背景经历」重复计数
  - 字节社招检索修复：搜索页只识别 `keywords` / `location`（旧参数 `keyword`、
    `location_code_list` 被 SPA 忽略，导致搜什么返回都一样）；保留城市后置过滤，
    多城市岗位命中目标城市保留，地点缺失无法核实者剔除
  - 文档与工具数同步（40 个工具）：README、docs/README、docs/llms.txt、docs/tools.md、
    workflow、session 手册更新「花名册→按需读取→子 Agent 汇总结论」协作方式

- **BOSS 直聘登录流程改为交互式关卡（实测：登录缺失被静默当失败）**：
  - `gather_research_data` 新增 `boss_confirmed`：调研范围含 BOSS 且未确认时返回
    `CONFIRMATION_REQUIRED`（附问题/选项），强制先问用户「是否抓取 BOSS」（需扫码登录）；
    已确认但 cookies 未就绪时返回 `LOGIN_REQUIRED`（附登录命令），先问用户
    「是否现在登录」，登录后带 `boss_confirmed=true` 重试；不再静默跳过或直接判失败
  - `fetch_company_jobs(company="boss")` 未登录时前置返回 `LOGIN_REQUIRED`
    （问题 + 登录命令 + 改用其他源/导入 JD 的恢复建议），抓取后遇到登录错误同样
    归为该码；非 BOSS 源行为不变
  - 调研 4 步模板与说明、会话手册、`docs/workflow.md` / `docs/llms.txt` /
    `docs/tools.md`、BOSS guide 同步「抓取前必须询问用户」的交互纪律

- **批量调研 bytedance 超时修复（单独调用成功、调研时报 20s timeout）**：
  - 根因：Playwright 首页热身 `goto(BASE_URL, timeout=20000)` 超时直接终止整次
    抓取——批量调研时 Edge 冷启动/站点波动更慢，比单独调用更易命中
  - 首页热身改为「尽力而为」（失败继续走搜索页，数据来自搜索页 XHR）；
    搜索页导航超时自动重试一次（30s × 2）；浏览器异常路径确保关闭不再泄漏

- **复测第二轮 8 项 BUG 修复（ec77aa6 复测，dev/test/BUG.md）**：
  - `save_current_detail` 孤儿阶段守卫补全：无路线图 / 缺 `phase_id` / 未知
    `phase_id` 一律拒绝（`MISSING_DATA` / `INVALID_PARAM`），不再产出孤儿 detail
  - GitHub 经验帖检索重做：岗位词与求职意图词（秋招/春招/面经/offer）改 **AND**
    组合（括号块，遵守 API 布尔运算符上限），`filter_company` 作必中条件参与
    检索；结果加标题门槛（标题必须带意图词或学历/公司条件），日文 issue、
    CI 修复、纯技术讨论一律过滤；零结果时降级宽 OR 查询仍保留标题门槛
  - 案例卡质量门：GitHub/牛客条目必须有求职意图词命中（标题或摘要），
    否则不进「同背景成功经验」；每张案例卡带 `hit_terms`（命中原因），
    `search_cases` 与调研报告逐条标注
  - 牛客面经摘要：列表页 snippet 缺失时逐条用详情页（SSR）meta description
    补水；仍取不到显式标 `snippet_status=unavailable`（位移展示「摘要未获取」），
    不再静默空串；`fetch_company_jobs` 输出同步提示
  - 调研报告：`direction` 显式传入时优先于档案 `want.target_role`（标题/上下文/
    汇报口径一致）；来源统计区分「JD 源」与「案例源」（案例源并入来源状态
    面板与数据缺口，汇报写清各自可用数）
  - 摸排提示：技能名回退链 `skill → name/title/tech`，取不到时「技能[索引] +
    条目摘录」并剥掉「用户确认：」前缀（不再只显示 `技能[0]` 无法定位）
  - 知识库检索打分重做：长词 2-gram 召回降权（0.05）且不参与文件名加分，
    整串仍正常计分——无意义查询总分低于阈值，不再混入 1 条弱相关结果

- **33 项实测 BUG 清单修复轮（dev/test/BUG.md，2006 会话实测）**：
  - P0 服务自检：新增 `server_fingerprint`——`start_session` 与 `fetch_company_jobs`
    错误信息都带「版本/工具数/代码路径」自检行，连错旧实例一眼可辨；
    doctor 与 BOSS 登录提示同步指引「重启会话切到当前代码」
  - P1 路线图机制重做（原阻断用户的主线）：
    - 层级模型升级：`intern` 目标 =「该阶段起点+1」直接合规（不再错误报警），
      支持阶段级 `start_level_after`（复评升级后后续阶段按新起点算，
      定稿时同步写回档案起点），「学习中厂 → 复评升级 → 冲大厂」路线可过审
    - `save_roadmap` 改「先校验后落盘」：硬校验（起点/层级连续/届别/必填/可执行性 lint）
      或上一轮审计 FAIL 时不落盘，返回问题清单；确认剩余风险后可显式 `force=true`
      带问题定稿，风险在返回值中显式复述
    - 新增 `save_roadmap_audit`（总 39 个工具）：auditor 审计结果落库
      （PASS/FAIL + issues），`save_roadmap` 只认最新落库记录；两轮 FAIL 后明确
      「结构性修正 / 带风险定稿」双出口，不再无限重审
    - 可执行性 lint：禁伞形任务名（「按专题刷题」）、禁时间节奏词（每周/每天，产品不排期）、
      量化 KPI 与任务计数不闭合时软提示
    - 阶段字段补全：`target_level` / `graduation_year` / `condition`（分支/备用路径）
      进入 `save_roadmap` 与 `sop/roadmap.yaml` 的 schema/审计清单，缺字段时给出软提示
  - P3 会话与档案状态：
    - `start_session` 按档案状态分流（已有任务直接续跑，不再对老用户复述欢迎手册）
    - `import_jd` 后旧差距分析标记过期，`get_workflow_status` 强制先 `analyze_gaps`
      重新分析，防止基于旧 JD 直接规划
    - `delete_profile` 拒绝删除当前使用中的档案（`PROFILE_IN_USE`，先 switch 再删）
    - 错误码细分：`PROFILE_NOT_FOUND` / `INVALID_PROFILE` / `PROFILE_IN_USE` /
      `INVALID_MODE`（导出）/ `INVALID_PARAM`（周检视 days 1-90 越界直接报错）
    - `apply_insight` 在 stage_audit 时点亮 `audited_phases`（仪表盘「已审计」标记可出现）
  - P2 数据源：
    - GitHub 经验帖：意图词减到 3 个避免 5 布尔运算符超限（422），
      降级为单关键词重搜
    - 牛客面经：snippet 超长判定为页面级文本直接丢弃；同片段整批置空；
      标题/摘要与搜索词毫无交集的串味条目过滤
    - 字节校招：搜索等待改 `domcontentloaded` + XHR 数据落地轮询，失败自动重试一次；
      响应按岗位 ID 去重；与关键词无交集的弱相关岗位过滤；
      未知参数在 loader 单点报错（不再静默吞掉）
    - 阿里校招/实习：过滤组合无结果时自动降级（去城市本地筛选 / 关键词放宽首段）
      并标注提示
    - `search_knowledge` 加相关度阈值（低分弱相关不返回，如实提示被截条数）
  - 分析质量门：AI 作者身份提示带真实技能名（取不到时带索引与条目摘录，不再是
    「技能[0]」占位）；`analyze_gaps` 在 `search_cases` 不可用时要求显式标注数据缺口

- **市场调研成为独立一步（批量抓取即落盘），产出入驻用户资产目录 CareerKit**：
  建档摸底后新增调研阶段，核心卖点「来源真实」——
  - 新增 2 工具（本段工具基数 37，后续第二轮增至 39）：`research_market`（调研方法论 + 4 步模板：范围宣告 →
    批量抓取 → 报告落地 → 衔接分析）与 `gather_research_data`（一次批量抓取：
    目标公司 1 家 + 对照 2-4 家真实 JD + 同学历经历案例，任一源失败不中断，
    失败原因原样进报告；全部失败时如实中止绝不编造）
  - 报告三件套（md 可读 / html 阅读版 / json 原始数据）由代码渲染落盘（不经 LLM），
    每条带来源链接与抓取时间；`profile.research` 同步更新，差距分析与路线图 jd
    三件套直接引用
  - 新用户资产目录 `~/CareerKit`（`CAREER_KIT_ASSETS_DIR` 可覆盖）：`index.html`
    资产总览唯一入口、中文目录名（调研报告/路线图/进度）、说明.md 首建；
    路线图与进度仪表盘改用固定文件名落盘（保浏览器打卡状态），程序数据
    `~/.career-kit` 与用户资产彻底分离
  - 流程升级为 6 步（建档摸底 → 市场调研 → 差距分析 → 路线图规划 → 执行打卡 →
    持续陪跑）：`analyze_gaps` step 2 改「读取调研」（直接引用调研报告，
    无调研给软提示后可 `search_cases` 兜底，不锁死）；workflow status 新增
    research 阶段判定；仪表盘新增「市场调研」卡片
  - 话术密度升级（播报三件套/完成汇报三要素/路径交付/未获取如实说）写入
    session 手册、两份命令剧本与 docs

- **首屏引导加全流程概览（用户实测反馈来即分析）**：/career-kit 发起后 AI 直接问个人情况，
  用户不知道要经历什么、每步会产出什么——
  - 第一轮回复改为两段式：先给「从起步到上岸全流程 5 步」概览模板
    （建档摸底 → 差距分析 → 路线图规划 → 执行打卡 → 持续陪跑，每步一行产出说明，
    「顺序定、节奏自己掌握」必留），再开始摸现状两问
  - 概览模板同步下发 4 载体（session.py 欢迎手册 / 两份命令剧本 / docs/llms.txt），
    新增防漂移测试：锚点四载体一致 + 两剧本概览块逐字一致

- **分析/规划过程透明化（黑盒感修复）**：真实运行测试反馈，LLM 按流程走但每步静默无输出，
  用户等很久只看到最终打分表——
  - `analyze_gaps` 新增 4 步 step_template（现状盘点 → 案例搜寻 → 两维分析 → 结果预览），
    checkpoint 步先展示用户确认、分析先讲方法论（为什么从简历过筛+面试通过两个维度看），
    结果预览经用户确认才落盘
  - 播报纪律全局化：「调用工具前一句话播报该步在干什么、在等什么」写入 analyze/roadmap
    指令、sop 原则、命令剧本与文档；表格/清单必须带「为什么」和依据
  - 案例搜寻纳入分析流程：`search_knowledge` 本地积累 + `fetch_jd_detail` 面经引用成为
    step 2 必选项，搜寻结果以案例卡片（带来源）展示给用户
  - 路线图 HTML 交付说明：定稿产物先解释用途与用法再给路径
  - 分析流程实测再校准：案例搜寻升级为独立步骤并 点名 `search_cases`
    （不得用散抓官方 JD 替代）；指令第一动作改为「先向用户报完整步骤菜单（步骤预告），
    报完再动手」，降低与分析等待期间的黑盒感

- **案例搜寻搜索聚合（search_cases 工具）**：
  - 新增 `search_cases` 工具（#35）：一次聚合本地知识库 + 牛客面经 + GitHub 经验帖 +
    BOSS/官方 JD（传 company 命中企业），按「同背景成功经验 / 面试要求」分类排序去重，
    输出带来源链接的案例卡与警告（源失败如实上报、不编造）
  - 新增 GitHub 数据源（Search API issues）：搜秋招/面经/offer 经验帖，
    自动打 `education_tag`（学历五档）/`year_tag`（届别）标签，未认证 10 次/分限流提示、
    经验帖写入 data/knowledge/experiences/
  - 新增 `src/education.py` 学历归一模块：五档四层（985/211/双非[含普本一二三本]/专科 ×
    博士/硕士/本科/专科 + 届别），双非本/211硕 等真实标题写法可解析，
    `education_match_beta` 给案例与用户背景分级匹配加分——双非本用户优先看到双非本案例

- **摸排盲区修复（BUG-021）**：真实运行测试发现，简历重度美化（代码全部 AI 生成）时
  摸排全关通过、match_score 虚高——AI 作者身份与把控度不建模，分析就会美化技能画像
  - 技能摸排升级为「求证 + 自评三问」：简历哪几条面试现场站得住（诚实回答）；
    每条技能标 `authorship`（self_written / ai_assisted / ai_generated / referenced）；
    把控度自评 `control_level` 0-10（3=讲架构，6=逐行讲清，8+=手写）；
    整份简历自评写 `have.self_assessment`——`authorship`/`control_level` 必须来自用户本人，AI 不得代填
  - `finalize_profile` 与 `analyze_gaps` 双保险硬门禁：缺自评即阻塞（`skip_probing=True` 仍是唯一用户主动旁路，留痕不变）
  - 内容质量门轻量扩展：存在 AI 作者身份技能时，`resume_red_flags` 必须含
    「AI 生成/手写」风险条目——不得静默吞掉；分析指令同步校准
    match_score 口径（按把控度打折、不贬损 AI-native 生产落地价值）、必加手写差距与分层面试准备
  - 话术纪律以 `src/tools/probing.py` 单一事实源下发：parse_resume / finalize 门禁 /
    session 手册 / 命令剧本 / sop 方法论（新增防漂移测试锁定）

## 0.1.0 - 2026-10-25

首个公开版本。

- **34 个 MCP 工具**：建档 → 差距分析 → 路线图 → 任务打卡 → 洞察调整 → 仪表盘产出
- **真实数据支撑**：接入 BOSS 直聘 / 字节 / 牛客 / 腾讯 / 百度 / 阿里招聘源，
  差距分析必须锚定真实数据来源，否则被内容质量门拒绝
- **求职漏斗**：投递 → 过筛 → 面试 → offer 全程记录（事件口径，面试后被拒仍计入面试数），
  转化率偏低时自动给出复盘提示
- **周检视**：一键生成周期复盘——打卡 / 阶段 / 漏斗事实 + 事实性建议，不倒手册不施压
- **可交互职业地图 / 进度仪表盘**：自包含 HTML，勾选即打卡、进度实时更新、浏览器本地保存
- **机制纪律**：顺序归产品、时间归用户（任务只有顺序与完成标准，无时限字段）；
  目标变更时已完成进度自动沉淀为能力证据，努力不白费
- **安装体检**：`career-kit-doctor` 一键诊断解释器 / 依赖 / 数据目录 / 配置
