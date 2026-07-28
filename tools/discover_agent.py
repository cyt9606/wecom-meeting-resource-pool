#!/usr/bin/env python3
"""Print the non-secret application IDs visible to the configured credential."""

from __future__ import annotations

import asyncio
import json

from app.config import get_settings
from app.wecom import WeComClient


async def main() -> None:
    settings = get_settings()
    client = WeComClient(settings.WECOM_CORP_ID, settings.WECOM_APP_SECRET)
    try:
        agents = await client.list_agents()
        print(
            json.dumps(
                [
                    {"agentid": item.get("agentid"), "name": item.get("name")}
                    for item in agents
                ],
                ensure_ascii=False,
            )
        )
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
