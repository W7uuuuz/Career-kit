# Career Kit

<!-- mcp-name: io.github.W7uuuuz/career-kit -->

[English](README.en.md) | 中文

[![CI](https://github.com/W7uuuuz/Career-kit/actions/workflows/ci.yml/badge.svg)](https://github.com/W7uuuuz/Career-kit/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![MCP](https://img.shields.io/badge/MCP-Compatible-green.svg)](https://modelcontextprotocol.io/)

> 别再海投了。Career Kit 是一个 AI 职业陪练 MCP 服务：抓真实岗位 → 分析差距 → 分阶段路线图 → 可打卡任务 → 求职漏斗复盘。

接入 Claude Code / Cursor / opencode / Codex，把你的求职从「投简历碰运气」变成「有真实数据支撑、可长期追踪」的计划。

![Career Kit 演示：投了 200 份没回音 → 真实岗位与同背景案例 → 差距诊断 → 下一步](docs/examples/demo/readme-demo.gif)

> **和你一样的人怎么走 → 你差哪一项 → 今天先做什么。**
> 演示数据为合成，不含真实用户简历或报告。

> **[点我 → 在线体验职业地图](https://w7uuuuz.github.io/Career-kit/examples/demo/career-map.html)**  
> 无需安装，直接勾选任务、看进度变化。

[示例产物](docs/examples/demo/) · [完整文档](docs/README.md)

## 30 秒看懂

- **真实数据，不瞎分析**：接入 BOSS / 字节 / 腾讯 / 百度 / 阿里 / 牛客 / GitHub 经验帖，AI 基于市场真实要求分析差距；差距必须锚定真实来源，否则被硬门禁拒绝。
- **拆成阶段任务**：分阶段、里程碑、可打卡任务（按次 / 按天 / 按比例），随时问「下一步做什么」。
- **求职漏斗可复盘**：投递 → 过筛 → 面试 → offer 全程记录（事件口径），「面试后被拒仍计入面试数」，让数据告诉你问题在简历还是面试。
- **周检视**：一键生成周期复盘（打卡 / 阶段 / 漏斗 + 事实性建议），隔一段时间回来也能立刻接续。
- **可交互职业地图**：一键导出自包含 HTML，勾选即打卡、进度实时更新、浏览器本地保存。
- **跟着你变，不是死计划**：拿到面试触发洞察重估；换目标时已完成进度自动沉淀为能力证据。
- **顺序归产品，时间归用户**：只为任务定义顺序与完成标准，不设时限。

> 如果这个项目帮你少走弯路，点一个 Star，让更多正在求职的人看到它。

## 60 秒体验（不安装）

- **在线版**：打开 [交互式职业地图](https://w7uuuuz.github.io/Career-kit/examples/demo/career-map.html)，直接勾选任务看进度变化。
- **本地版**：双击 `docs/examples/demo/career-map.html`，或安装后运行 `career-kit-demo`。
- 想看完整链路：`docs/examples/demo/` 里有样例简历生成的路线图、进度仪表盘和原始档案。

## 它怎么工作

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

## 为什么是它

| | ChatGPT | 求职网站 | Career Kit |
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

## 快速开始

### 方式一：pipx 安装（推荐）

`pipx` 会把命令装进独立环境，不污染系统 Python，也不需要记 uv 的用法。

```bash
# 安装 pipx（只需一次）
python -m pip install --user pipx
python -m pipx ensurepath

# 安装 Career Kit
pipx install career-kit

# 体检
career-kit-doctor
```

> Windows 提示 `career-kit` 不是命令时，重开终端，或执行 `python -m pipx ensurepath`。
> 镜像未同步时：`pipx install --pip-args="--index-url https://pypi.org/simple" career-kit`。

### 方式二：uvx 免安装

已经装了 [uv](https://docs.astral.sh/uv/) 的话，可以完全不安装：

```bash
uvx --from career-kit career-kit-doctor   # 安装体检
uvx --from career-kit career-kit          # 启动 MCP 服务（stdio）
```

> 镜像未同步或安装 `iv8` 失败时，加官方索引：
> `uvx --from career-kit --default-index https://pypi.org/simple career-kit`。

### 注册到你的 AI Agent

| Agent | pipx / pip 安装后 | uvx 免安装 |
|-------|------------------|------------|
| Claude Code | `claude mcp add career-kit -- career-kit` | `claude mcp add career-kit -- uvx --from career-kit career-kit` |
| Codex CLI | `codex mcp add career-kit -- career-kit` | `codex mcp add career-kit -- uvx --from career-kit career-kit` |
| opencode | `{"mcp": {"career-kit": {"type": "local", "command": ["career-kit"], "enabled": true}}}` | `{"mcp": {"career-kit": {"type": "local", "command": ["uvx", "--from", "career-kit", "career-kit"], "enabled": true}}}` |
| Cursor / Windsurf | command=`career-kit` | command=`uvx`，args=`["--from", "career-kit", "career-kit"]` |

### 方式三：源码安装

```bash
git clone https://github.com/W7uuuuz/Career-kit.git
cd Career-kit
pip install -e .
```

> **解释器很重要**：注册命令里的 `python` 必须是执行过 `pip install -e .` 的那一个。本机有多个 Python 时，裸 `python` 可能指向缺依赖的解释器。最稳妥是 venv 绝对路径：
> `D:\path\to\Career-kit\.venv\Scripts\python.exe`（Windows）或 `.venv/bin/python`（macOS/Linux）。

注册命令（把 `<venv-python>` 换成你的绝对路径）：

```bash
claude mcp add career-kit -- <venv-python> -m src.server
codex mcp add career-kit -- <venv-python> -m src.server
```

opencode 配置：

```json
{"mcp": {"career-kit": {"type": "local", "command": ["<venv-python>", "-m", "src.server"], "enabled": true}}}
```

> macOS 用户把 python 换成 python3。opencode 的 `.opencode/config.json` 不是 MCP 注册入口，改它是无效的。

### 方式四：一键安装脚本

```bash
# macOS / Linux
bash install.sh

# Windows PowerShell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

脚本会建好 `.venv`、装好依赖，并直接打印注册命令（使用绝对解释器路径）。

### 本地控制台（可选）

```bash
career-kit-serve --open
# 或
"<venv-python>" -m src.web --open
```

只监听 `127.0.0.1`，用于查看路线图、任务怎么做 / 资源 / 完成标准并直接打卡；还可以编辑任务、登记投递、按方向筛选调研报告，并通过 SSE 自动刷新。打卡写入同一份 SQLite 档案，MCP 下次运行时直接读到。

### 验证安装

```bash
career-kit-doctor
# 或
"<venv-python>" -m src.doctor
```

全部 OK 后，对新会话说「调用 start_session」，或直接敲 `/career-kit`——收到「欢迎使用 Career Kit」即接入成功。

### 常见问题

| 现象 | 处理 |
|------|------|
| `pipx` / `uvx` 报找不到 `career-kit`，或安装 `iv8` 失败 | 默认镜像未同步：pipx 加 `--pip-args="--index-url https://pypi.org/simple"`；uvx 加 `--default-index https://pypi.org/simple` |
| `No module named 'mcp'` | 注册用了错误解释器，改用 venv 绝对路径或 `uvx` |
| 抓取报 Playwright 相关错误 | 先执行 `playwright install chromium` |
| BOSS 提示需要登录 | 由 Agent 运行登录脚本并打开浏览器，你只需扫码 |
| 工具列表里没有 career-kit | 先跑 `career-kit-doctor`，再检查 Agent 的 MCP 连接状态 |

## 文档

- [文档地图](docs/README.md)：所有文档的唯一入口
- [LLM 使用指南](docs/llms.txt)：工作流、规则、常见场景
- [工作流详解](docs/workflow.md)：各阶段前置条件、输入输出
- [工具总览](docs/tools.md)：41 个 MCP 工具的唯一事实源
- [企业库](docs/scrapers.md)：已收录企业、数据源说明
- [知识库](docs/knowledge.md)：目录结构、文件格式
- [示例](docs/examples/README.md)：可交互职业地图与场景示例
- [贡献指南](CONTRIBUTING.md) · [行为准则](CODE_OF_CONDUCT.md) · [安全策略](SECURITY.md)

## 适合谁

- **适合你，如果你**：在找工作或转行、会用 Claude Code / opencode 这类 AI 编程工具、想要一份「有真实岗位数据支撑、可长期追踪」的计划。
- **暂不适合你，如果你**：完全没有命令行使用经验。当前形态需要安装 Python + 注册 MCP，Web / 无安装版本在规划中。

## 贡献

欢迎 issue、PR 和新的企业数据源。开始前请读 [CONTRIBUTING.md](CONTRIBUTING.md)；新增企业源请参考 `src/scrapers/_template/`。

如果这个项目帮你少走了弯路，点一个 Star 就是最好的支持——它会让更多正在求职的人看到它。

## 开源协议

MIT
