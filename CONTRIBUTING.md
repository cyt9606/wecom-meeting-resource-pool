# Contributing

欢迎提交 Issue 和 Pull Request。

## 开发流程

1. Fork 仓库并从 `main` 创建功能分支。
2. 后端改动运行 `pytest -q`。
3. 前端改动运行 `pnpm test` 和 `pnpm build`。
4. 不要提交 `.env`、企业微信 Secret、真实 userid、会议链接、会议号或生产日志。
5. Pull Request 中说明改动目的、验证方式和可能的兼容性影响。

安全问题请按 [SECURITY.md](SECURITY.md) 的方式报告，不要公开提交包含凭据或生产数据的 Issue。
