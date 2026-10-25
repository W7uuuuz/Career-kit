# 贡献指南

感谢你对 Career Kit 的兴趣！

## 如何贡献

### 报告问题

发现 Bug 或有新想法？[开一个 Issue](https://github.com/W7uuuuz/Career-kit/issues/new)。

### 贡献代码

1. Fork 本仓库
2. 创建你的分支：`git checkout -b feature/your-feature`
3. 提交你的改动：`git commit -m "feat: 添加你的功能"`
4. 推送到你的 Fork：`git push origin feature/your-feature`
5. 开一个 Pull Request

### 贡献企业 Scraper

想让更多企业的数据进入 Career Kit？

1. 复制模板：`cp -r src/scrapers/_template src/scrapers/{company_name}`
2. 实现 `search()` 和 `get_detail()` 方法
3. 填写包内 `guide.md` 使用教程（LLM 运行时按需读取，缺文件会挂测试）
4. 在 `src/scrapers/config.yaml` 注册
5. 提交 PR

详见 [企业库文档](docs/scrapers.md)。

### 环境体检

首次配置或遇到启动问题时：

```bash
python -m src.doctor
```

需要检查浏览器内核/数据源连通性时：

```bash
python -m src.doctor --browser --network
```

### 端到端测试

新增功能或修改工作流后，至少跑核心 E2E：

```bash
python tests/e2e/cli.py --suite core
```

真实数据源、浏览器交互、LLM Agent 是独立 opt-in 套件：

```bash
python tests/e2e/cli.py --suite live --sources tencent,baidu,alibaba
python tests/e2e/cli.py --suite browser
python tests/e2e/cli.py --suite llm
```

质量评分与优化清单输出在 `artifacts/e2e/<run-id>/`，说明见
[tests/e2e/README.md](tests/e2e/README.md)。

## 开发规范

### 提交信息

使用 [Conventional Commits](https://www.conventionalcommits.org/) 格式：

- `feat:` 新功能
- `fix:` 修复 Bug
- `docs:` 文档更新
- `chore:` 构建/工具变动

### 代码风格

- Python 3.11+
- 类型提示
- 文档字符串

提交前跑 lint 与单元测试（CI 同样会跑）：

```bash
ruff check src tests
pytest tests --ignore=tests/e2e -q
```

## 问题？

有问题随时开 Issue，我们会尽快回复。
