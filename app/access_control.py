from __future__ import annotations


PUBLIC_PATHS = {
    "/health",
}

WECOM_ONLY_ERROR_PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>访问受限</title>
  <style>
    body{margin:0;background:#f7f7f5;color:#111;font-family:system-ui,sans-serif}
    main{max-width:560px;margin:12vh auto;padding:40px;background:#fff;border:1px solid #deded9}
    p{color:#6f6f6a;line-height:1.8}small{display:block;margin-top:28px;color:#999}
  </style>
</head>
<body><main><h1>请从企业微信工作台进入</h1>
<p>当前访问环境不是企业微信客户端，会议资源池已拒绝本次访问。</p>
<small>错误代码：WECOM_CLIENT_REQUIRED</small></main></body>
</html>"""


def is_wecom_user_agent(user_agent: str | None) -> bool:
    return "wxwork" in (user_agent or "").lower()


def is_public_path(path: str) -> bool:
    return path in PUBLIC_PATHS
