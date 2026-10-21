# Career Kit E2E

不是只看「有没有报错」，而是量化「功能效果好不好」：

- **阻断性**：工具是否成功、状态是否落盘、协议是否可用
- **效果性**：差距是否有来源、路线图是否可执行、任务是否具体、产出是否可交互
- **可优化性**：每次运行输出 `quality.json` / `quality.md`，直接列出低分项

默认单测不会收集本目录；使用 `cli.py` 或显式设置 `CAREER_KIT_E2E=1`。

## 快速开始

```bash
# 核心套件：无网络、无 LLM、无浏览器
python tests/e2e/cli.py --suite core

# 真实数据源（腾讯/百度/阿里）
python tests/e2e/cli.py --suite live --sources tencent,baidu,alibaba

# 浏览器交互（需要 playwright install chromium）
python tests/e2e/cli.py --suite browser

# 真实 LLM Agent（需要 ANTHROPIC_API_KEY）
python tests/e2e/cli.py --suite llm

# 全部
python tests/e2e/cli.py --suite all
```

## 覆盖范围

| 套件 | 内容 | 依赖 |
|------|------|------|
| core | 全链路、简历/摸排、重启续跑、多档案、守卫与恢复 | 无 |
| live | 真实招聘站点搜索/详情/知识库落盘 | 网络 |
| browser | HTML 打开、勾选打卡、localStorage、重置 | Chromium |
| llm | Agent 选工具、守规则、最终档案状态 | LLM API |

核心套件覆盖 30/32 个工具；`fetch_company_jobs` / `fetch_jd_detail` 由 live 套件覆盖。

## 产物

```
artifacts/e2e/<run-id>/<test>/
├── transcript.jsonl    # 每次 MCP 调用（工具、参数、返回、耗时）
├── server.log          # MCP Server stderr
├── quality.json        # 质量评分
├── quality.md          # 可读优化清单
├── data/               # 失败时的档案/知识库快照
└── llm-transcript.json # LLM 套件对话与工具调用
```

失败默认保留沙箱；成功清理。设置 `CAREER_KIT_E2E_KEEP=1` 可强制保留。

## 质量评分

| 维度 | 关注点 |
|------|--------|
| 目标具体度 | 目标岗位、城市、薪资、目标公司 |
| 技能证据 | 技能是否有用户确认的证据 |
| 差距质量 | `source` 覆盖、`match_score`、行动建议、红牌对策、起点层级 |
| 路线图质量 | 阶段数、里程碑完成标准、KPI 量化、简历价值、JD 依据、无时长字段 |
| 任务质量 | 阶段绑定、打卡模式、命名具体度、去重、状态合法 |
| 指引质量 | 返回是否给出下一步、是否提到具体工具 |
| 产出质量 | 数据快照、交互元素、阶段渲染、自包含 |
| 数据质量（live） | title/url/company/location 完整、去重、详情厚度 |

核心断言：总分 ≥ 70，且单项 ≥ 50；LLM 套件额外看工具覆盖与错误率。

## 环境变量

| 变量 | 作用 |
|------|------|
| `CAREER_KIT_E2E` | 启用 E2E 收集 |
| `CAREER_KIT_E2E_ARTIFACTS` | 自定义产物目录 |
| `CAREER_KIT_E2E_KEEP` | 成功也保留沙箱 |
| `CAREER_KIT_E2E_LIVE` | 启用真实数据源 |
| `CAREER_KIT_E2E_SOURCES` | 指定 live 源，逗号分隔 |
| `ANTHROPIC_API_KEY` | LLM 套件必需 |
| `CAREER_KIT_E2E_LLM_MODEL` | LLM 模型名 |
| `CAREER_KIT_E2E_LLM_BASE_URL` | Anthropic 兼容端点 |

## 设计约束

1. 每个测试使用独立 `CAREER_KIT_DATA_DIR`、HOME、TMP，不触碰真实 `~/.career-kit`。
2. 所有业务调用走真实 MCP stdio，不直接调用工具函数。
3. 核心套件不依赖外网；live/LLM/browser 独立 opt-in。
4. 失败保留 transcript 与数据快照，便于复现和优化。
