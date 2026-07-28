# Security Policy

## Reporting

请通过 GitHub Security Advisory 私下报告安全问题。不要在公开 Issue 中粘贴企业微信
CorpID、应用 Secret、access token、真实 userid、会议号、入会链接或服务器日志。

## Deployment notes

- 所有 Secret 仅通过环境变量或权限受控文件注入。
- 生产环境应使用 HTTPS，并通过主机防火墙、安全组等措施限制非必要的网络访问。
- `REQUIRE_WECOM_CLIENT` 的 User-Agent 检查只是客户端来源限制，不是密码学安全边界。
- 实际身份与权限必须继续依赖企业微信 OAuth、服务端会话和数据库授权。
- 部署前请为自建应用配置最小必要的通讯录和会议接口权限。
