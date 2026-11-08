# Career Kit

English | [中文](https://github.com/W7uuuuz/Career-kit/blob/main/README.md)

[![CI](https://github.com/W7uuuuz/Career-kit/actions/workflows/ci.yml/badge.svg)](https://github.com/W7uuuuz/Career-kit/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![MCP](https://img.shields.io/badge/MCP-Compatible-green.svg)](https://modelcontextprotocol.io/)

> Not sure what job to pursue? Career Kit is an AI career coach as an MCP server — grounded in real postings and peer-path evidence, it helps you pick a direction, see your gap clearly, and break out one next step you can act on today. Works with Claude Code, Cursor, opencode, and Codex.

![Career Kit demo: not sure what job to pursue → peer paths → gap diagnosis → next step](https://raw.githubusercontent.com/W7uuuuz/Career-kit/main/docs/examples/demo/readme-demo.gif)

> **See where people like you went and what employers require → your gap → one next step.**
> Demo data is synthetic; the demo UI is in Chinese.

<div align="center">

### [Try it → 3-minute online simulation](https://w7uuuuz.github.io/Career-kit/examples/demo/chat-demo.html)

Chat with the coach via fixed options and walk the whole flow; scripted demo with synthetic data. Install locally for real use.

</div>

[Sample output](https://github.com/W7uuuuz/Career-kit/tree/main/docs/examples/demo) · [Docs](https://github.com/W7uuuuz/Career-kit/blob/main/docs/README.md)

## Understand it in 30 seconds: twelve stages from start to landing

Each stage makes one decision and delivers one artifact; order is fixed, pace is yours:

1. **Profile establishment** — verify the resume point by point to establish a real, auditable level and goal.
2. **Target role positioning** — set direction, city, target tier, and bridge tier.
3. **Market baseline research** — fetch real postings and interview reports into a sourced market baseline.
4. **Capability gap diagnosis** — compare market requirements against current state.
5. **Training plan design** — break the goal into ordered phases and tasks.
6. **Target company selection** — turn tiers into a user-confirmed company pool.
7. **Job and interview evidence collection** — collect real JDs and interview reports with sources and confidence; optionally add BOSS for salary and broader coverage.
8. **Company requirement analysis** — extract high-frequency requirements, per-JD hard filters, and interview topics.
9. **Execution plan calibration** — align the baseline plan with the requirement profile.
10. **Task execution and check-ins** — work through tasks and turn completions into capability evidence.
11. **Application management** — build a ranked application list from the evidence pool, then record applications, interviews, offers, and funnel conversion.
12. **Periodic review and plan adjustment** — review facts and detect plan drift when data or goals change.

> If this project helps you, a star is appreciated.

## Supported sites

Data comes from 46 collected sources across internet / AI, manufacturing / energy, and hardware / semiconductors:

- **Company career sources (43)**: ByteDance / Tencent / Alibaba / Baidu / Meituan / NetEase / JD / Kuaishou / Pinduoduo / Xiaohongshu / Bilibili / Xiaomi / DiDi / Ctrip / Vipshop / DJI / Dewu / Soul / MiniMax and other internet, AI, and gaming companies, plus Huawei / BOE / Sany / CRRC / Inovance / Sungrow in manufacturing, energy, and hardware — gap analysis works beyond the internet industry too.
- **Recruiting platform**: BOSS Zhipin — public salary ranges for market-rate context.
- **Experience posts**: Nowcoder interview reports and GitHub experience threads, as evidence of how people with the same background got through.

The company catalog lists 64 companies, 42 of which are auto-scrapable; the rest are marked for manual application.

**[All sources, data types, and usage guides →](https://github.com/W7uuuuz/Career-kit/blob/main/docs/scrapers.md)** · community additions welcome ([CONTRIBUTING.md](https://github.com/W7uuuuz/Career-kit/blob/main/CONTRIBUTING.md), see `src/scrapers/_template/`); scraping reads public pages only.

## How it works

Install Career Kit and register the MCP service with your agent, then just say "use Career Kit" in the conversation. The `/career-kit` slash command is specific to Claude Code / opencode and only available when the session runs inside the source repository; other agents (including ChatGPT desktop and Doubao Work) start it by conversation.

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

Under the hood: 49 MCP tools covering onboarding, profile management, data acquisition (including market research), analysis and planning, company alignment, tasks and funnel, and insight generation. Full list and call timing in [tools.md](https://github.com/W7uuuuz/Career-kit/blob/main/docs/tools.md).

## Compared with other job-hunting tools

| | Plain AI chat | Job sites | Career Kit |
|---|---------|----------|------------|
| Real postings | None | Yes | Yes (scraped, with salary) |
| Personalized roadmap | Generic advice | None | Phases + milestones + done criteria |
| Staged task check-ins | None | None | Once / daily / percent |
| Progress tracking | None | None | Phase audits + event insights |
| Local data, self-hosted | No | No | Yes |

## Privacy and boundaries

- Data stays local: program data in `~/.career-kit/` (SQLite profile `career-kit.db`, JSON mirroring for compatibility), reports and roadmaps in `~/CareerKit/`. Nothing is sent to any external server.
- The knowledge base is a user asset and survives package upgrades.
- Scraping only reads public job and interview pages; respect each site's terms and rate limits. This project offers no referrals, guaranteed offers, or any employment promise. See [DISCLAIMER.md](https://github.com/W7uuuuz/Career-kit/blob/main/DISCLAIMER.md).

## Who it is for

Unemployed students; no career plan; unsure what job to pursue; switching careers without a clear starting point; or applying repeatedly without knowing what is missing — plus the ability to use an AI tool with local MCP support such as Claude Code, Codex, opencode, ChatGPT desktop, or Doubao Work. If that describes you, Career Kit is worth a try.

## Quick start

**Recommended: hand the installation to your AI agent.** Send the project URL to a terminal agent such as Claude Code / Codex / opencode; it reads the docs and handles install, registration, and self-check:

```text
Install and register Career Kit for me: https://github.com/W7uuuuz/Career-kit
Follow the README "Quick start" — install with pipx (or uvx), register as a local MCP service, run career-kit-doctor, and report the result when done.
```

<details>
<summary>Manual install and registration — click to expand</summary>

**pipx** (isolated environment, no system pollution):

```bash
# Install pipx (once)
python -m pip install --user pipx
python -m pipx ensurepath

# Install Career Kit
pipx install career-kit
```

**uvx, no install** (if you already use [uv](https://docs.astral.sh/uv/)):

```bash
uvx --from career-kit career-kit-doctor   # self-check
uvx --from career-kit career-kit          # start the MCP server (stdio)
```

**Register**: add `career-kit` as a local MCP service (uvx users: command is `uvx --from career-kit career-kit`):

| Agent | Configuration |
|-------|----------|
| Claude Code | `claude mcp add career-kit -- career-kit` |
| Codex CLI | `codex mcp add career-kit -- career-kit` |
| opencode | `{"mcp": {"career-kit": {"type": "local", "command": ["career-kit"], "enabled": true}}}` |
| Cursor / Windsurf | command=`career-kit` |
| ChatGPT desktop | Settings → MCP servers → Add server, STDIO, command=`career-kit` |
| Doubao Work (PC client) | Connector center → New custom plugin, STDIO, command=`career-kit` |

</details>

### Verify

```bash
career-kit-doctor
```

Then say "call start_session" to your agent in a new session; "Welcome to Career Kit" means the setup is done.

> For source install, one-click scripts, the local console, and troubleshooting, see the [Install guide](https://github.com/W7uuuuz/Career-kit/blob/main/docs/install.md).

## Documentation

- [Documentation map](https://github.com/W7uuuuz/Career-kit/blob/main/docs/README.md)
- [LLM usage guide](https://github.com/W7uuuuz/Career-kit/blob/main/docs/llms.txt)
- [Workflow](https://github.com/W7uuuuz/Career-kit/blob/main/docs/workflow.md)
- [Install guide](https://github.com/W7uuuuz/Career-kit/blob/main/docs/install.md): source install, one-click script, local console, troubleshooting
- [Tools](https://github.com/W7uuuuz/Career-kit/blob/main/docs/tools.md): the single source of truth for the 49 MCP tools
- [Data sources](https://github.com/W7uuuuz/Career-kit/blob/main/docs/scrapers.md)
- [Knowledge base](https://github.com/W7uuuuz/Career-kit/blob/main/docs/knowledge.md)
- [Examples](https://github.com/W7uuuuz/Career-kit/blob/main/docs/examples/README.md)
- [Contributing](https://github.com/W7uuuuz/Career-kit/blob/main/CONTRIBUTING.md) · [Code of Conduct](https://github.com/W7uuuuz/Career-kit/blob/main/CODE_OF_CONDUCT.md) · [Security](https://github.com/W7uuuuz/Career-kit/blob/main/SECURITY.md)

## Contributing

Issues, PRs, and new company data sources are welcome. Read [CONTRIBUTING.md](https://github.com/W7uuuuz/Career-kit/blob/main/CONTRIBUTING.md) first; new scrapers can start from `src/scrapers/_template/`.

If this project saves you a wrong turn, a star helps more job seekers find it.

## License

MIT
