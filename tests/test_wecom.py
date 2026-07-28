import httpx
import pytest
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
