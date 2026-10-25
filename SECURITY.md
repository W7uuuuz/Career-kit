# 安全策略

## 报告安全漏洞

发现安全问题请使用 GitHub 的 **Security Advisories / 私密报告**,
**不要**在公开 Issue 里描述可被利用的细节。

- 入口：本仓库 Security 标签页 → Report a vulnerability
- 我们会在 7 天内确认，修复后随下一个版本发布并致谢（如你愿意）

## 范围

Career Kit 是本地 MCP 服务，设计上：

- 所有用户数据（档案、知识库、缓存、登录态）只存放在本地 `~/.career-kit/`，不上传
- 联网仅发生在你主动调用抓取工具（企业招聘站检索）与可选的网络体检

## 特别提醒：登录 cookie 属敏感数据

BOSS 直聘抓取依赖扫码登录，登录态与浏览器 profile 保存在：

```
~/.career-kit/cache/boss/
```

其中包含你的登录 cookie。**不要分享、截图或打包上传这个目录**；
提交 issue 附日志时，请先检查输出里不含 cookie / token 字样。

## 支持的版本

| 版本 | 支持 |
|------|------|
| 最新 main / 最新 Release | 支持 |
| 更早版本 | 建议升级后反馈 |
