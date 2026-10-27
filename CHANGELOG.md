# Changelog

## Unreleased

- **行业扫盲子流程 + 通用数据层（2026-10-27）**：
  - 第一轮先判断行业认知，再决定是否扫盲；扫盲是可选子流程，拒绝不阻塞规划
  - 行业为入口（MVP 互联网/软件行业），专业降为可选个性化字段
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
