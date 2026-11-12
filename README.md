# Career Kit

<!-- mcp-name: io.github.W7uuuuz/career-kit -->

[English](https://github.com/W7uuuuz/Career-kit/blob/main/README.en.md) | 中文

[![CI](https://github.com/W7uuuuz/Career-kit/actions/workflows/ci.yml/badge.svg)](https://github.com/W7uuuuz/Career-kit/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![MCP](https://img.shields.io/badge/MCP-Compatible-green.svg)](https://modelcontextprotocol.io/)

> 不知道做什么工作？Career Kit 是一个 AI 职业陪练 MCP 服务——以真实岗位数据和同背景案例为依据，帮你确定方向、看清差距、拆解出当下即可执行的一步。可接入 Claude Code / Cursor / opencode / Codex。

![Career Kit 演示：不知道做什么工作 → 同背景的人怎么走 → 差距诊断 → 下一步](https://raw.githubusercontent.com/W7uuuuz/Career-kit/main/docs/examples/demo/readme-demo.gif)

> **先看同背景的人去了哪，企业招聘需要什么 → 再看你差在哪 → 今天先做什么。**
> 演示数据为合成，不含真实用户简历或报告。

<div align="center">

### [点我 → 3分钟在线模拟体验](https://w7uuuuz.github.io/Career-kit/examples/demo/chat-demo.html)

无需安装，像和 AI 教练对话一样走完整个流程；演示为固定选项对话与合成数据，真实使用请安装到本地。

</div>

[示例产物](https://github.com/W7uuuuz/Career-kit/tree/main/docs/examples/demo) · [完整文档](https://github.com/W7uuuuz/Career-kit/blob/main/docs/README.md)

## 30 秒看懂：定位 → 规划 → 执行

全流程 12 步，归为三段。每段只解决一类问题，关键节点由你确认。

| 阶段 | 包含步骤 | 你会拿到 |
|---|---|---|
| **定位** | 1 职业档案 · 2 目标岗位 · 3 市场基线 · 4 差距诊断 | 确认过的真实水平、目标岗位和差距清单 |
| **规划** | 5 基线方案 · 6 目标企业 · 7 JD/面经 · 8 企业需求 · 9 执行校准 | 针对具体企业/JD 的执行版路线图 |
| **执行** | 10 任务打卡 · 11 投递管理 · 12 周期复盘 | 能力证据、投递漏斗和持续维护 |

顺序固定、节奏自定；每阶段只做一个决策，无证据的结论不会写进方案。

> 如果这个项目对你有帮助，欢迎点一个 Star。

## 适合谁

未就业大学生；没有职业规划；不知道做什么工作；想转行但不知从何入手；或正在求职但屡屡碰壁说不清差距所在

并且能使用 Claude Code / Codex / opencode / ChatGPT 桌面客户端 / 豆包工作（PC 客户端）这类支持本地 MCP 的 AI 工具——满足这些条件，Career Kit 就值得试。

## 与其他求职工具的对比

| | 普通AI对话 | 求职网站 | Career Kit |
|---|---------|----------|------------|
| 真实岗位数据 | 无 | 有 | 有（可抓取，含薪资） |
| 个性化路线图 | 泛泛而谈 | 无 | 分阶段 + 里程碑 + 完成标准 |
| 阶段任务打卡 | 无 | 无 | 有（按次 / 按天 / 按比例） |
| 进度追踪调整 | 无 | 无 | 阶段审计 + 事件洞察 |
| 数据本地、可自托管 | 否 | 否 | 是 |

## 快速开始

**推荐：把安装交给你的 AI Agent。** 将项目地址发给 Claude Code / Codex / opencode 等终端 Agent，它会自行阅读文档完成安装、注册与自检：

```text
帮我安装并注册 Career Kit：https://github.com/W7uuuuz/Career-kit
按其 README「快速开始」用 pipx（或 uvx）安装，注册为本地 MCP 服务，运行 career-kit-doctor 自检，通过后告诉我结果。
```

<details>
<summary>手动安装（pipx / uvx）与 GUI 客户端注册 - 点击展开</summary>

**pipx 安装**（将命令装进独立环境，不污染系统 Python）：

```bash
# 安装 pipx（只需一次）
python -m pip install --user pipx
python -m pipx ensurepath

# 安装 Career Kit
pipx install career-kit
```

**uvx 免安装**（已安装 [uv](https://docs.astral.sh/uv/) 时可跳过安装）：

```bash
uvx --from career-kit career-kit-doctor   # 安装自检
uvx --from career-kit career-kit          # 启动 MCP 服务（stdio）
```

**注册**：将 `career-kit` 注册为本地 MCP 服务（uvx 用户把命令换成 `uvx --from career-kit career-kit`）：

| Agent | 配置 |
|-------|------|
| Claude Code | `claude mcp add career-kit -- career-kit` |
| Codex CLI | `codex mcp add career-kit -- career-kit` |
| opencode | `{"mcp": {"career-kit": {"type": "local", "command": ["career-kit"], "enabled": true}}}` |
| Cursor / Windsurf | command=`career-kit` |
| ChatGPT 桌面客户端 | Settings → MCP servers → Add server，STDIO，command=`career-kit` |
| 豆包工作（PC 客户端） | 连接器中心 → 新建自定义插件，STDIO，命令=`career-kit` |

</details>

### 验证安装

```bash
career-kit-doctor
```

全部通过后，在新会话中对 Agent 说「调用 start_session」，收到「欢迎使用 Career Kit」即接入成功。

> 源码安装 / 一键安装脚本 / 实时职业地图（FastAPI + Vue）/ 常见问题，见[安装指南](https://github.com/W7uuuuz/Career-kit/blob/main/docs/install.md)。

## 支持哪些网站

数据来自 59 个已收录数据源，覆盖 **互联网/AI、制造/能源、硬件/半导体、金融** 行业（持续新增，欢迎社区PR更新）：

- **企业招聘源（55 个）**：字节 / 腾讯 / 阿里 / 百度 / 美团 / 网易 / 京东 / 快手 / 拼多多 / 小红书 / B站 / 小米 / 滴滴 / 携程 / 唯品会 / 大疆 / 得物 / Soul / MiniMax 等互联网、AI 与游戏公司，以及华为 / 京东方 / 三一 / 中车 / 汇川技术 / 阳光电源等制造 / 能源 / 硬件企业——互联网之外的方向也能做差距分析。
- **招聘平台**：实习僧（近一月实习岗位，大厂/中厂实习优先参考，可核验日薪、每周天数、实习月数与转正机会）、BOSS 直聘（公开岗位薪资范围，用于薪资与广度补充），覆盖金融等行业的实习机会。
- **经验帖**：来自牛客网面经与 GitHub 上岸经验库，用于佐证「同等背景的人如何走通」。

企业目录收录 90 家，其中 54 家可自动抓取；其余标注为需手动投递。

**[查看全部数据源、数据类型与使用教程 →](https://github.com/W7uuuuz/Career-kit/blob/main/docs/scrapers.md)** · 新数据源欢迎社区补充（[贡献指南](https://github.com/W7uuuuz/Career-kit/blob/main/CONTRIBUTING.md)，参考 `src/scrapers/_template/`）；抓取仅读取公开页面。

## 工作方式

安装 Career Kit 并在 Agent 中注册 MCP 服务后，对话直接说「使用 Career Kit」即可启动。斜杠命令 `/career-kit` 为 Claude Code / opencode 专属，且仅当会话在源码仓库目录内打开时可用；其余 Agent（含 ChatGPT 桌面客户端、豆包工作）用对话启动即可。

```
你：我想转 AI Agent 方向
Career Kit：分析差距 → 拉取真实岗位数据 → 设计路线图 → 拆成阶段任务

你：我不知道想做什么，帮我选个方向
Career Kit：三轴定位（能力 × 兴趣 × 真实岗位数据）→ 候选方向 → 引导选定

你：这步做完了
Career Kit：打卡记录 → 沉淀能力证据 → 阶段完成自动审计

你：我拿到大厂面试了
Career Kit：事件触发洞察 → 重估计划 → 调整阶段任务
```

底层是 51 个 MCP 工具，覆盖建档、档案管理、数据获取（含市场调研）、证据引用、分析规划、企业适配、任务与漏斗、洞察产出八大类。完整清单与调用时机见[工具总览](https://github.com/W7uuuuz/Career-kit/blob/main/docs/tools.md)。

## 隐私与数据边界

- 程序数据存储在本地 `~/.career-kit/`（档案主存储为 `career-kit.db`，JSON 为兼容镜像），调研报告存储在 `~/CareerKit/`，职业地图由本地控制台按档案实时渲染；所有数据都不会发送到任何外部服务器。
- 知识库是用户自有资产，不随包升级丢失。
- 抓取只读取公开岗位 / 面经页面，请遵守来源站点条款与频率限制；本项目不提供内推、保 offer 或任何就业承诺。详见 [DISCLAIMER.md](https://github.com/W7uuuuz/Career-kit/blob/main/DISCLAIMER.md)。

## 文档

- [文档地图](https://github.com/W7uuuuz/Career-kit/blob/main/docs/README.md)：所有文档的唯一入口
- [LLM 使用指南](https://github.com/W7uuuuz/Career-kit/blob/main/docs/llms.txt)：工作流、规则、常见场景
- [工作流详解](https://github.com/W7uuuuz/Career-kit/blob/main/docs/workflow.md)：各阶段前置条件、输入输出
- [安装指南](https://github.com/W7uuuuz/Career-kit/blob/main/docs/install.md)：源码安装、一键脚本、实时职业地图、常见问题
- [工具总览](https://github.com/W7uuuuz/Career-kit/blob/main/docs/tools.md)：51 个 MCP 工具的唯一事实源
- [企业库](https://github.com/W7uuuuz/Career-kit/blob/main/docs/scrapers.md)：已收录企业、数据源说明
- [知识库](https://github.com/W7uuuuz/Career-kit/blob/main/docs/knowledge.md)：目录结构、文件格式
- [示例](https://github.com/W7uuuuz/Career-kit/blob/main/docs/examples/README.md)：可交互职业地图与场景示例
- [贡献指南](https://github.com/W7uuuuz/Career-kit/blob/main/CONTRIBUTING.md) · [行为准则](https://github.com/W7uuuuz/Career-kit/blob/main/CODE_OF_CONDUCT.md) · [安全策略](https://github.com/W7uuuuz/Career-kit/blob/main/SECURITY.md)

## 贡献

欢迎 issue、PR 与新的企业数据源。开始前请先阅读 [CONTRIBUTING.md](https://github.com/W7uuuuz/Career-kit/blob/main/CONTRIBUTING.md)；新增企业源请参考 `src/scrapers/_template/`。

如果这个项目帮你少走了弯路，一个 Star 会帮助更多求职者发现它。

## 开源协议

MIT
