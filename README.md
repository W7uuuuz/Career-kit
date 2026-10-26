# Career Kit

[![CI](https://github.com/W7uuuuz/Career-kit/actions/workflows/ci.yml/badge.svg)](https://github.com/W7uuuuz/Career-kit/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![MCP](https://img.shields.io/badge/MCP-Compatible-green.svg)](https://modelcontextprotocol.io/)

> 别再海投了。AI 帮你规划路线、打卡执行、达成目标。

**Career Kit 是一个 MCP 服务**——接入 Claude Code / Cursor / opencode 等任意支持 MCP 的 AI Agent，
把你的求职从「投简历碰运气」变成「有真实数据支撑的分阶段计划 + 可打卡执行」。

![Career Kit 职业地图](docs/examples/demo/career-map.png)

> 上图是 `docs/examples/demo/career-map.html` 的真实截图——一份样例简历经完整链路生成的
> **可交互职业地图**（勾选打卡、进度实时更新、本地保存）。无需安装，双击即可打开体验。

## 30 秒看懂

- **真实数据，不瞎分析**：接入 BOSS / 字节 / 腾讯 / 百度 / 阿里 / 牛客等真实岗位数据，
  AI 基于市场真实要求分析差距；差距必须锚定真实数据来源，否则被硬门禁拒绝。
- **拆成阶段任务**：分阶段、里程碑、可打卡任务（按次/按天/按比例），随时问「下一步做什么」。
- **求职漏斗可复盘**：投递 → 过筛 → 面试 → offer 全程记录（事件口径），
  「面试后被拒仍计入面试数」；转化的问题是简历还是面试，让数据开口说话。
- **周检视**：一键生成周期复盘（打卡 / 阶段 / 漏斗 + 事实性建议），过段时间回来也能立刻接续。
- **可交互职业地图**：一键导出自包含 HTML，勾选即打卡、进度实时更新、浏览器本地保存。
- **跟着你变，不是死计划**：拿到面试触发洞察重估；换目标时已完成进度自动沉淀为能力证据。
- **顺序归产品，时间归用户**：只为任务定义顺序与完成标准，不为它设时限。

## 快速开始

### 一键安装（推荐）

```bash
# macOS / Linux
bash install.sh

# Windows PowerShell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

脚本会建好 `.venv`、装好依赖，并直接打印注册命令——**用绝对解释器路径**，
避开「裸 `python` 指到错误解释器」的经典坑。

### 手动安装

```bash
git clone https://github.com/W7uuuuz/Career-kit.git
cd Career-kit
pip install -e .
```

> **解释器很重要**：注册命令里的 `python` 必须是执行过 `pip install -e .` 的那一个。
> 本机存在多个 Python 时，裸 `python` 可能指向缺依赖的解释器。最稳妥是 venv 绝对路径：
> `D:\path\to\Career-kit\.venv\Scripts\python.exe`（Windows）或 `.venv/bin/python`（macOS/Linux）。

### 注册到你的 AI Agent

| Agent | 注册方式 |
|-------|---------|
| Claude Code | `claude mcp add career-kit -- <venv-python> -m src.server` |
| Codex CLI | `codex mcp add career-kit -- <venv-python> -m src.server` |
| opencode | 项目根目录 `opencode.json`（或全局 `~/.config/opencode/opencode.jsonc`）加入：`{"mcp": {"career-kit": {"type": "local", "command": ["<venv-python>", "-m", "src.server"], "enabled": true}}}` |
| Cursor / Windsurf | MCP 设置中手动添加：command=`<venv-python>`，args=`["-m", "src.server"]` |

> macOS 用户把 python 换成 python3。
> opencode 的 `.opencode/config.json` 不是 MCP 注册入口，改它是无效的。

### 验证安装

先跑体检：

```bash
"<venv-python>" -m src.doctor
# 或安装后
career-kit-doctor
```

全部 OK 后，对新会话说「调用 start_session」，或直接敲 `/career-kit`——
收到「欢迎使用 Career Kit」欢迎信息即接入成功。

### 故障排查

| 现象 | 处理 |
|------|------|
| 工具列表里没有 career-kit 的工具 | 先运行 `career-kit-doctor`；确认注册命令在 Career-kit 目录下执行；Claude Code 会话内用 `/mcp` 查看连接状态 |
| 服务器启动即崩 / `No module named 'mcp'` | 注册用了错误解释器——改用 venv 绝对路径（见上方警告） |
| 抓取工具报 Playwright 相关错误 | 先执行 `playwright install chromium` 安装浏览器内核 |
| BOSS 直聘提示需要登录 | 按报错信息里的绝对解释器命令运行 `-m src.scrapers.boss.login`，扫码后自动保存 |
| uv 装依赖报 `iv8 was not found` | iv8 只在官方 PyPI，不在镜像上：`uv pip install -e . --index-url https://pypi.org/simple` |

### 斜杠命令（可选）

- **Claude Code**：仓库已内置 `/career-kit [目标]` 与 `/career-kit-profile`。在任意目录使用：
  `mkdir -p ~/.claude/commands && cp .claude/commands/*.md ~/.claude/commands/`
- **opencode**：内置 `.opencode/commands/`，全局版复制到 `~/.config/opencode/commands/`
- **Codex CLI**：把 `.claude/commands/*.md` 复制为 `~/.codex/prompts/`

## 它能做什么？

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

## 为什么是它？

| | ChatGPT | 求职网站 | Career Kit |
|---|---------|----------|------------|
| 真实岗位数据 | 无 | 有 | 有（可抓取，含薪资） |
| 个性化路线图 | 泛泛而谈 | 无 | 分阶段 + 里程碑 + 完成标准 |
| 阶段任务打卡 | 无 | 无 | 有（按次/按天/按比例） |
| 进度追踪调整 | 无 | 无 | 阶段审计 + 事件洞察 |
| 数据本地、可自托管 | 否 | 否 | 是 |

## 工具与文档

40 个 MCP 工具覆盖建档、档案管理、数据获取（含市场调研）、分析规划、任务与漏斗、洞察产出六大类。
完整清单与调用时机见[工具总览](docs/tools.md)，文档全貌见[文档地图](docs/README.md)；
LLM 运行时还会通过 MCP Resources 自动读取工作流和企业库。

- [文档地图](docs/README.md)：所有文档的唯一入口
- [LLM 使用指南](docs/llms.txt)：工作流、规则、常见场景
- [工作流详解](docs/workflow.md)：各阶段前置条件、输入输出
- [工具总览](docs/tools.md)：40 个 MCP 工具的唯一事实源
- [企业库](docs/scrapers.md)：已收录企业、数据源说明
- [知识库](docs/knowledge.md)：目录结构、文件格式
- [示例](docs/examples/README.md)：可交互职业地图与场景示例

## 适合谁

- 适合你，如果你：在找工作或转行、会用 Claude Code / opencode 这类 AI 编程工具、
  想要一份「有真实岗位数据支撑、可长期追踪」的计划。
- 暂不适合你，如果你：完全没有命令行使用经验。当前形态需要安装 Python + 注册 MCP，
  Web / 无安装版本在规划中。

## 隐私

所有数据存储在本地 `~/.career-kit/`，不会发送到任何外部服务器。
知识库是用户自有资产，不随包升级丢失。

## 开源协议

MIT
