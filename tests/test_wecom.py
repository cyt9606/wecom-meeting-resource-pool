import httpx
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock

from app.wecom import WeComClient, WeComError


@pytest.mark.asyncio
async def test_access_token_is_cached():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={"errcode": 0, "access_token": "token", "expires_in": 7200},
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = WeComClient("corp", "secret", http=http)
    assert await client.access_token() == "token"
    assert await client.access_token() == "token"
    assert calls == 1
    await client.close()


def test_join_info_uses_only_fields_returned_by_api():
    result = WeComClient.join_info(
        {
            "meeting_link": "https://meeting.example/join",
            "meeting_number": 123456789,
            "settings": {"password": "2468"},
        }
    )
    assert result == {
        "external_join_url": "https://meeting.example/join",
        "numeric_meeting_code": "123456789",
        "password": "2468",
    }


@pytest.mark.asyncio
async def test_cancel_is_idempotent_when_meeting_is_already_cancelled():
    client = WeComClient("corp", "secret")
    client.api = AsyncMock(
        side_effect=WeComError("取消会议", 400041, "meeting has been canceled")
    )

    await client.cancel_meeting("meeting-1")
    await client.close()


@pytest.mark.asyncio
async def test_create_meeting_sends_password_and_waiting_room():
    client = WeComClient("corp", "secret")
    client.api = AsyncMock(return_value={"errcode": 0, "meetingid": "meeting-1"})

    meetingid = await client.create_meeting(
        admin_userid="advanced",
        host_userid="requester",
        title="安全会议",
        start_at=datetime.now(timezone.utc),
        duration_minutes=60,
        description="说明",
        allow_external_user=False,
        password="2468",
        enable_waiting_room=True,
    )

    assert meetingid == "meeting-1"
    payload = client.api.await_args.kwargs["payload"]
    assert payload["settings"]["password"] == "2468"
    assert payload["settings"]["enable_waiting_room"] is True
    assert payload["settings"]["allow_external_user"] is False
    await client.close()


@pytest.mark.asyncio
async def test_update_meeting_sends_all_editable_fields_and_clears_password():
    client = WeComClient("corp", "secret")
    client.api = AsyncMock(return_value={"errcode": 0})
    start_at = datetime.now(timezone.utc)

    await client.update_meeting(
        "meeting-1",
        title="新主题",
        start_at=start_at,
        duration_minutes=90,
        description="新说明",
        allow_external_user=True,
        password=None,
        set_password=True,
        enable_waiting_room=True,
    )

    payload = client.api.await_args.kwargs["payload"]
    assert payload["title"] == "新主题"
    assert payload["meeting_start"] == int(start_at.timestamp())
    assert payload["meeting_duration"] == 90 * 60
    assert payload["description"] == "新说明"
    assert payload["settings"] == {
        "allow_external_user": True,
        "password": "",
        "enable_waiting_room": True,
    }
    await client.close()
