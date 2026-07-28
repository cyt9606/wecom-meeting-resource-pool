#!/usr/bin/env python3
"""Production smoke test: schedule, verify, and immediately cancel one meeting."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timedelta, timezone

from app.config import get_settings
from app.db import Database
from app.models import ReservationCreate
from app.repositories import Repository
from app.scheduler import Scheduler
from app.wecom import WeComClient


async def main() -> int:
    settings = get_settings()
    applicant = os.environ.get("WECOM_MEETING_HOST_USERID", "").strip()
    if not applicant:
        raise RuntimeError("WECOM_MEETING_HOST_USERID is missing")
    start_offset_minutes = int(
        os.environ.get("WECOM_SMOKE_START_OFFSET_MINUTES", "45")
    )

    database = Database(settings.DATABASE_URL)
    database.initialize()
    repository = Repository(database)
    repository.sync_resources(settings.WECOM_MEETING_RESOURCE_USERIDS)
    client = WeComClient(
        settings.WECOM_CORP_ID,
        settings.WECOM_APP_SECRET,
        settings.WECOM_AGENT_ID,
    )
    reservation = None
    try:
        request = ReservationCreate(
            title="资源池上线验收",
            start_at=datetime.now(timezone.utc)
            + timedelta(minutes=start_offset_minutes),
            duration_minutes=30,
            description="部署后端到端验收，创建成功后立即取消。",
            allow_external_user=False,
        )
        reservation = await Scheduler(repository, client).create(
            applicant,
            request,
            f"deployment-smoke-{uuid.uuid4()}",
        )
        info = await client.get_meeting_info(reservation["meetingid"])
        summary = {
            "created": True,
            "reservation_id": str(reservation["id"]),
            "meetingid": reservation["meetingid"],
            "resource_display_name": reservation.get("resource_display_name"),
            "host_confirmed": Scheduler.applicant_is_host(info, applicant),
            "has_external_join_url": bool(
                client.join_info(info).get("external_join_url")
            ),
            "has_numeric_meeting_code": bool(
                client.join_info(info).get("numeric_meeting_code")
            ),
        }
        print(json.dumps(summary, ensure_ascii=False))
        await client.cancel_meeting(reservation["meetingid"])
        repository.mark_cancelled(reservation["id"])
        print(
            json.dumps(
                {
                    "cancelled": True,
                    "reservation_id": str(reservation["id"]),
                },
                ensure_ascii=False,
            )
        )
        return 0
    finally:
        await client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
