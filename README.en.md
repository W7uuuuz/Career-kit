# Career Kit

English | [中文](README.md)

[![CI](https://github.com/W7uuuuz/Career-kit/actions/workflows/ci.yml/badge.svg)](https://github.com/W7uuuuz/Career-kit/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![MCP](https://img.shields.io/badge/MCP-Compatible-green.svg)](https://modelcontextprotocol.io/)

> Not sure what job to pursue? Career Kit is an AI career coach MCP server: real postings and peer paths → direction → gap analysis → one next step.

Works with Claude Code, Cursor, opencode, and Codex. It helps you choose a direction, close the right gaps, and take the next step.

![Career Kit demo: not sure what job to pursue → peer paths → gap diagnosis → next step](docs/examples/demo/readme-demo.gif)

> **See where people like you went → the real requirements → your gap → one next step.**
> Demo data is synthetic; the demo UI is in Chinese.

> **[Click here to try the interactive career map](https://w7uuuuz.github.io/Career-kit/examples/demo/career-map.html)**  
> No install; check a task and watch progress update.

[Sample output](docs/examples/demo/) · [Docs](docs/README.md)

## Why it is different

- **Real data, not guesses**: pulls live postings from BOSS, ByteDance, Tencent, Baidu, Alibaba, Nowcoder, and GitHub experience threads. Gap analysis must cite real sources or it is rejected.
- **Staged tasks**: phases, milestones, and check-in tasks (once / daily / percent). Ask "what should I do next" at any time.
- **Application funnel**: track applied → screened → interview → offer with event-based accounting. A rejection after an interview still counts as an interview.
- **Weekly review**: a factual recap of check-ins, phases, and funnel changes, so you can resume after a break.
- **Interactive career map**: export a self-contained HTML file. Check tasks, watch progress update, persist locally.
- **Adapts to you**: getting an interview triggers a re-evaluation; switching goals turns completed work into capability evidence.
- **Order is the product's job; pace is yours**: no deadlines are imposed on tasks.

> If this saves you time, a star helps more job seekers find it.

## Try it in 60 seconds (no install)

- **Online**: open the [interactive career map](https://w7uuuuz.github.io/Career-kit/examples/demo/career-map.html) and check a task.
- **Local**: open `docs/examples/demo/career-map.html`, or run `career-kit-demo` after installing.
- Full pipeline sample: `docs/examples/demo/` contains the roadmap, progress dashboard, and raw profile.

## How it works

```
You: I want to move into AI Agent engineering.
Career Kit: gap analysis → fetch real postings → design a roadmap → break it into staged tasks

You: I don't know what to do. Help me choose a direction.
Career Kit: three-axis positioning (skills × interests × real market data) → candidate directions → pick one

You: Done with this step.
Career Kit: check-in → capability evidence → automatic phase audit

You: I got a big-tech interview.
Career Kit: event-triggered insight → re-evaluate the plan → adjust tasks
```

Under the hood: 41 MCP tools covering onboarding, profile management, data acquisition (including market research), analysis and planning, tasks and funnel, and insight generation. See [tools.md](docs/tools.md).

## Privacy and boundaries

- Data stays local: `~/.career-kit/` for program data, `~/CareerKit/` for reports and roadmaps. Nothing is sent to an external server.
- Scraping only reads public job and interview pages. Respect each site's terms and rate limits. No referrals, no guaranteed offers. See [DISCLAIMER.md](DISCLAIMER.md).

## Quick start

### Option 1: pipx (recommended)

`pipx` installs the CLI in an isolated environment without touching your system Python.

```bash
python -m pip install --user pipx
python -m pipx ensurepath
pipx install career-kit
career-kit-doctor
```

> On Windows, reopen the terminal or run `python -m pipx ensurepath` if
> `career-kit` is not found. If your mirror has not synced the release:
> `pipx install --pip-args="--index-url https://pypi.org/simple" career-kit`.

### Option 2: uvx (no install)

If you already use [uv](https://docs.astral.sh/uv/):

```bash
uvx --from career-kit career-kit-doctor   # health check
uvx --from career-kit career-kit          # start the MCP server (stdio)
```

> If your package mirror has not synced the release or fails on `iv8`, add
> `--default-index https://pypi.org/simple`.

### Register with your agent

| Agent | pipx / pip | uvx |
|-------|-----------|-----|
| Claude Code | `claude mcp add career-kit -- career-kit` | `claude mcp add career-kit -- uvx --from career-kit career-kit` |
| Codex CLI | `codex mcp add career-kit -- career-kit` | `codex mcp add career-kit -- uvx --from career-kit career-kit` |
| opencode | `{"mcp": {"career-kit": {"type": "local", "command": ["career-kit"], "enabled": true}}}` | `{"mcp": {"career-kit": {"type": "local", "command": ["uvx", "--from", "career-kit", "career-kit"], "enabled": true}}}` |
| Cursor / Windsurf | command=`career-kit` | command=`uvx`, args=`["--from", "career-kit", "career-kit"]` |

### Option 3: from source

```bash
git clone https://github.com/W7uuuuz/Career-kit.git
cd Career-kit
pip install -e .
```

Use the same interpreter that ran `pip install -e .` when registering:

```bash
claude mcp add career-kit -- <venv-python> -m src.server
codex mcp add career-kit -- <venv-python> -m src.server
```

### Option 4: install script

```bash
bash install.sh                 # macOS / Linux
powershell -ExecutionPolicy Bypass -File .\install.ps1   # Windows
```

### Local console (optional)

```bash
career-kit-serve --open
```

Binds to `127.0.0.1` only. View the roadmap, task instructions, resources, and done criteria; check in directly; edit tasks and record applications. Data is written to the same SQLite profile the MCP server reads.

### Verify

```bash
career-kit-doctor
```

Then ask your agent to call `start_session`.

## Documentation

- [Documentation map](docs/README.md)
- [LLM usage guide](docs/llms.txt)
- [Workflow](docs/workflow.md)
- [Tools](docs/tools.md)
- [Data sources](docs/scrapers.md)
- [Knowledge base](docs/knowledge.md)
- [Examples](docs/examples/README.md)
- [Contributing](CONTRIBUTING.md) · [Code of Conduct](CODE_OF_CONDUCT.md) · [Security](SECURITY.md)

## Who it is for

- **Good fit**: you are not sure what job to pursue, switching careers without a clear starting point, or already applying but unsure what is missing; you use an AI coding agent.
- **Not yet**: you have no command-line experience. The current form requires Python and MCP registration.

## Contributing

Issues, PRs, and new company data sources are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) first; new scrapers can start from `src/scrapers/_template/`.

If this project saves you time, a star helps more job seekers find it.

## License

MIT
