## 改动内容

<!-- 一句话说明改了什么，以及为什么 -->

## 关联 Issue

<!-- 如 Fixes #123；没有可写「无」 -->

## 验证

- [ ] `ruff check src tests`
- [ ] `pytest tests --ignore=tests/e2e -q`
- [ ] 涉及流程改动时跑了 e2e core
- [ ] 涉及界面改动时附了截图或录屏

## 数据源变更（如适用）

- [ ] 新增/修改了 `src/scrapers/<id>/`
- [ ] 已更新 `src/scrapers/<id>/guide.md`
- [ ] 已在 `src/scrapers/config.yaml` 注册
- [ ] 已在 `src/scrapers/companies.yaml` 补充档位、行业、别名与 scraper 映射
- [ ] 已在 `docs/scrapers.md` 补充说明
