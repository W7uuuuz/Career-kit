# Career Kit

<!-- mcp-name: io.github.W7uuuuz/career-kit -->

[English](README.en.md) | 中文

[![CI](https://github.com/W7uuuuz/Career-kit/actions/workflows/ci.yml/badge.svg)](https://github.com/W7uuuuz/Career-kit/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![MCP](https://img.shields.io/badge/MCP-Compatible-green.svg)](https://modelcontextprotocol.io/)

> 不知道做什么工作？Career Kit 是一个 AI 职业陪练 MCP 服务——以真实岗位数据和同背景案例为依据，帮你确定方向、看清差距、拆解出当下即可执行的一步。可接入 Claude Code / Cursor / opencode / Codex。

![Career Kit 演示：不知道做什么工作 → 同背景的人怎么走 → 差距诊断 → 下一步](docs/examples/demo/readme-demo.gif)

> **先看同背景的人去了哪，企业招聘需要什么 → 再看你差在哪 → 今天先做什么。**
> 演示数据为合成，不含真实用户简历或报告。

> **[点我 → 在线体验对话式陪练](https://w7uuuuz.github.io/Career-kit/examples/demo/chat-demo.html)**  
> 无需安装，像和 AI 教练对话一样走完整个流程；演示为固定选项对话与合成数据。

[示例产物](docs/examples/demo/) · [完整文档](docs/README.md)

## 30 秒看懂：从起步到上岸的 6 个阶段

每个阶段都会交付实际产物，顺序固定、节奏自定：

1. **建档摸底**——通过简历和对话，弄清用户真实水平和目标，得到一份真实的用户档案。
2. **市场调研**——抓取真实岗位与面经，得到一份带来源链接的市场报告，看看同层次的其他人是怎么做的。
3. **差距分析**——对照市场要求与用户现状，得到一份可执行的差距清单。
4. **路线图规划**——把用户的目标拆成有顺序的阶段和任务，得到一张可打卡的职业地图。
5. **执行打卡**——逐项推进任务，完成即沉淀为能力证据。
6. **持续陪跑**——周期复盘打卡 / 阶段 / 求职漏斗，目标变化时随时重新规划。

> 如果这个项目对你有帮助，欢迎点一个 Star。

## 支持哪些网站

数据来自 27 个已收录数据源，支持 **互联网/制造/能源/硬件** 行业（持续新增，欢迎社区PR更新）：

- **企业官网招聘专区（24 个）**：字节 / 腾讯 / 阿里 / 百度 / 美团 / 网易 / 京东 / 快手 / 拼多多 / 小红书 / B站 / 小米 / 滴滴 / 携程等互联网公司，以及华为 / 京东方 / 三一 / 中车 / 汇川技术 / 阳光电源等制造 / 能源 / 硬件企业——互联网之外的方向也能做差距分析。
- **招聘平台**：BOSS 直聘，公开岗位薪资范围，薪酬行情以此为依据。
- **经验帖**：来自牛客网面经与 GitHub 上岸经验库，用于佐证「同等背景的人如何走通」。

**[查看全部数据源、数据类型与使用教程 →](docs/scrapers.md)** · 新数据源欢迎社区补充（[贡献指南](CONTRIBUTING.md)，参考 `src/scrapers/_template/`）；抓取仅读取公开页面。

## 60 秒在线体验

打开 [在线对话演示](https://w7uuuuz.github.io/Career-kit/examples/demo/chat-demo.html)，用固定选项模拟和 AI 教练对话，走完「方向 → 建档 → 调研 → 差距 → 路线」全流程，预制的职业地图在对话尽头揭晓；[也可直接查看职业地图](https://w7uuuuz.github.io/Career-kit/examples/demo/career-map.html)。

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

底层是 41 个 MCP 工具，覆盖建档、档案管理、数据获取（含市场调研）、分析规划、任务与漏斗、洞察产出六大类。完整清单与调用时机见[工具总览](docs/tools.md)。

## 与其他求职工具的对比

| | 普通AI对话 | 求职网站 | Career Kit |
|---|---------|----------|------------|
| 真实岗位数据 | 无 | 有 | 有（可抓取，含薪资） |
| 个性化路线图 | 泛泛而谈 | 无 | 分阶段 + 里程碑 + 完成标准 |
| 阶段任务打卡 | 无 | 无 | 有（按次 / 按天 / 按比例） |
| 进度追踪调整 | 无 | 无 | 阶段审计 + 事件洞察 |
| 数据本地、可自托管 | 否 | 否 | 是 |

## 隐私与数据边界

- 程序数据存储在本地 `~/.career-kit/`（档案主存储为 `career-kit.db`，JSON 为兼容镜像），报告与路线图存储在 `~/CareerKit/`，不会发送到任何外部服务器。
- 知识库是用户自有资产，不随包升级丢失。
- 抓取只读取公开岗位 / 面经页面，请遵守来源站点条款与频率限制；本项目不提供内推、保 offer 或任何就业承诺。详见 [DISCLAIMER.md](DISCLAIMER.md)。

## 适合谁

未就业大学生；没有职业规划；不知道做什么工作；想转行但不知从何入手；或正在求职但屡屡碰壁说不清差距所在

并且能使用 Claude Code / Codex / opencode / ChatGPT 桌面客户端 / 豆包工作（PC 客户端）这类支持本地 MCP 的 AI 工具——满足这些条件，Career Kit 就值得试。

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

> 源码安装 / 一键安装脚本 / 本地控制台 / 常见问题，见[安装指南](docs/install.md)。

## 文档

- [文档地图](docs/README.md)：所有文档的唯一入口
- [LLM 使用指南](docs/llms.txt)：工作流、规则、常见场景
- [工作流详解](docs/workflow.md)：各阶段前置条件、输入输出
- [安装指南](docs/install.md)：源码安装、一键脚本、本地控制台、常见问题
- [工具总览](docs/tools.md)：41 个 MCP 工具的唯一事实源
- [企业库](docs/scrapers.md)：已收录企业、数据源说明
- [知识库](docs/knowledge.md)：目录结构、文件格式
- [示例](docs/examples/README.md)：可交互职业地图与场景示例
- [贡献指南](CONTRIBUTING.md) · [行为准则](CODE_OF_CONDUCT.md) · [安全策略](SECURITY.md)

## 贡献

欢迎 issue、PR 与新的企业数据源。开始前请先阅读 [CONTRIBUTING.md](CONTRIBUTING.md)；新增企业源请参考 `src/scrapers/_template/`。

如果这个项目帮你少走了弯路，一个 Star 会帮助更多求职者发现它。

## 开源协议

MIT
