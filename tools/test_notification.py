#!/usr/bin/env python3
"""Send one clearly labelled deployment notification to the configured test user."""

from __future__ import annotations

import asyncio
import json
import os

from app.config import get_settings
from app.wecom import WeComClient


async def main() -> None:
    settings = get_settings()
    userid = os.environ.get("WECOM_MEETING_HOST_USERID", "").strip()
    if not userid:
        raise RuntimeError("WECOM_MEETING_HOST_USERID is missing")
    client = WeComClient(
        settings.WECOM_CORP_ID,
        settings.WECOM_APP_SECRET,
        settings.WECOM_AGENT_ID,
    )
    try:
        sent = await client.send_text(
            userid,
            "【高级会议资源池】上线验证通知\n"
            "应用消息通道测试成功，无需处理。",
        )
        print(json.dumps({"notification_sent": sent}))
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
