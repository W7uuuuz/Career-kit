# 安装指南

> 主 README 只保留推荐路径（pipx / uvx）。本文承载其余安装方式、
> 本地控制台与常见问题。

## 源码安装

```bash
git clone https://github.com/W7uuuuz/Career-kit.git
cd Career-kit
pip install -e .
```

**解释器很重要**：注册命令里的 `python` 必须是执行过 `pip install -e .`
的那个解释器。本机存在多个 Python 时，裸 `python` 可能指向缺少依赖的环境，
推荐改用 venv 解释器的绝对路径：

- Windows：`D:\path\to\Career-kit\.venv\Scripts\python.exe`
- macOS / Linux：`/path/to/Career-kit/.venv/bin/python`

注册命令（把 `<venv-python>` 替换为解释器的绝对路径）：

```bash
claude mcp add career-kit -- <venv-python> -m src.server
codex mcp add career-kit -- <venv-python> -m src.server
```

opencode 配置：

```json
{"mcp": {"career-kit": {"type": "local", "command": ["<venv-python>", "-m", "src.server"], "enabled": true}}}
```

> macOS 下将 `python` 替换为 `python3`。opencode 的 `.opencode/config.json`
> 不是 MCP 注册入口，修改它不会生效。

源码安装后，在源码仓库目录内打开会话即可使用 Claude Code / opencode 的
斜杠命令 `/career-kit`（命令文件随仓库发布：`.claude/commands/`、
`.opencode/commands/`）。

## 一键安装脚本

```bash
# macOS / Linux
bash install.sh

# Windows PowerShell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

脚本会创建 `.venv`、安装依赖，并输出注册命令（使用解释器绝对路径）。

## 本地控制台（可选）

```bash
career-kit-serve --open
# 或（源码安装）
"<venv-python>" -m src.web --open
```

控制台后端为 FastAPI（uvicorn）应用，前端为 Vue 单页应用，构建产物放在
`src/web_ui/dist`；缺失构建产物时访问 `/` 会返回 503 与构建提示。
仅监听 `127.0.0.1`，用于查看路线图与任务详情（怎么做 / 资源 / 完成标准）
并直接打卡；也支持编辑任务、登记投递、按方向筛选调研报告，并通过 SSE
自动刷新。打卡写入同一份 SQLite 档案，MCP 下次运行时即可读取。

## 常见问题

| 现象 | 处理 |
|------|------|
| Windows 提示 `career-kit` 不是命令 | 重开终端，或执行 `python -m pipx ensurepath` |
| `pipx` / `uvx` 报找不到 `career-kit`，或安装 `iv8` 失败 | 默认镜像未同步：pipx 加 `--pip-args="--index-url https://pypi.org/simple"`；uvx 加 `--default-index https://pypi.org/simple` |
| `No module named 'mcp'` | 注册使用了错误的解释器，改用 venv 绝对路径或 `uvx` |
| 抓取报浏览器相关错误 | 飞书等源优先使用系统 Chrome / Edge；未安装时再执行 `playwright install chromium` 使用内置 Chromium |
| BOSS 直聘提示需要登录 | 由 Agent 运行登录脚本并打开浏览器，用户只需扫码 |
| 工具列表中没有 career-kit | 先运行 `career-kit-doctor`，再检查 Agent 的 MCP 连接状态 |
| 源码安装后 `/career-kit` 不出现 | 该命令仅在 Claude Code / opencode 中可用，且需在源码仓库目录内打开会话；其余 Agent 用对话启动 |
