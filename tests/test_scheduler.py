from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from app.models import ReservationCreate
from app.scheduler import ResourceUnavailable, Scheduler


START = datetime.now(timezone.utc) + timedelta(hours=2)


class FakeRepository:
    def __init__(self):
        self.resource = {
            "id": uuid4(),
            "wecom_userid": "resource-owner",
            "display_name": "高级会议资源 01",
        }
        self.confirmed = None
        self.failed = None

    def find_by_idempotency(self, applicant, key):
        return None

    def get_policy(self):
        return {
            "buffer_minutes": 10,
            "min_lead_minutes": 15,
            "max_duration_minutes": 480,
            "max_advance_days": 90,
            "max_pending_per_user": 10,
        }

    def count_pending(self, applicant):
        return 0

    def list_resources(self):
        return [self.resource]

    def hold(self, **kwargs):
        return {
            "id": uuid4(),
            "status": "HELD",
            "title": kwargs["title"],
            "start_at": kwargs["start_at"],
            "end_at": kwargs["end_at"],
            "created_at": START,
            "updated_at": START,
        }

    def mark_creating(self, reservation_id):
        pass

    def fail_and_release(self, reservation_id, error_code, error_message):
        self.failed = (reservation_id, error_code, error_message)

    def confirm_created(self, reservation_id, meetingid, join_info):
        self.confirmed = {
            "id": reservation_id,
            "status": "CREATED",
            "title": "项目评审",
            "start_at": START,
            "end_at": START + timedelta(hours=1),
            "meetingid": meetingid,
            "join_info_json": join_info,
            "created_at": START,
            "updated_at": START,
        }
        return self.confirmed


@pytest.mark.asyncio
async def test_create_assigns_applicant_as_host_and_confirms():
    repository = FakeRepository()
    wecom = AsyncMock()
    wecom.get_user_meeting_ids.return_value = []
    wecom.create_meeting.return_value = "meeting-1"
    wecom.get_meeting_info.return_value = {
        "settings": {"hosts": {"userid": ["requester"]}},
        "meeting_link": "https://example/join",
    }
    wecom.join_info.return_value = {
        "external_join_url": "https://example/join"
    }
    wecom.join_info = Mock(
        return_value={"external_join_url": "https://example/join"}
    )
    wecom.send_text.return_value = False
    scheduler = Scheduler(repository, wecom)

    result = await scheduler.create(
        "requester",
        ReservationCreate(
            title="项目评审",
            start_at=START,
            duration_minutes=60,
        ),
        "request-key-123456789",
    )

    assert result["meetingid"] == "meeting-1"
    wecom.create_meeting.assert_awaited_once()
    assert (
        wecom.create_meeting.await_args.kwargs["admin_userid"]
        == "resource-owner"
    )
    assert wecom.create_meeting.await_args.kwargs["host_userid"] == "requester"
    assert wecom.create_meeting.await_args.kwargs["password"] is None
    assert (
        wecom.create_meeting.await_args.kwargs["enable_waiting_room"] is False
    )
    wecom.update_meeting.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_repairs_host_then_confirms():
    repository = FakeRepository()
    wecom = AsyncMock()
    wecom.get_user_meeting_ids.return_value = []
    wecom.create_meeting.return_value = "meeting-1"
    wecom.get_meeting_info.side_effect = [
        {"settings": {"hosts": {"userid": []}}},
        {
            "settings": {"hosts": {"userid": ["requester"]}},
            "meeting_link": "https://example/join",
            "meeting_number": "123456789",
        },
    ]
    wecom.join_info = Mock(
        return_value={
            "external_join_url": "https://example/join",
            "numeric_meeting_code": "123456789",
        }
    )
    wecom.send_text.return_value = False
    scheduler = Scheduler(repository, wecom)

    result = await scheduler.create(
        "requester",
        ReservationCreate(
            title="项目评审",
            start_at=START,
            duration_minutes=480,
        ),
        "request-key-123456789",
    )

    assert result["status"] == "CREATED"
    wecom.update_meeting.assert_awaited_once_with(
        "meeting-1",
        host_userid="requester",
        admin_userid="resource-owner",
    )


@pytest.mark.asyncio
async def test_create_accepts_applicant_as_creator_host():
    repository = FakeRepository()
    repository.resource["wecom_userid"] = "resource-owner"
    wecom = AsyncMock()
    wecom.get_user_meeting_ids.return_value = []
    wecom.create_meeting.return_value = "meeting-1"
    wecom.get_meeting_info.return_value = {
        "creator_userid": "resource-owner",
        "admin_userid": "resource-owner",
        "settings": {"hosts": {"userid": []}},
        "meeting_link": "https://example/join",
        "meeting_number": "123456789",
    }
    wecom.join_info = Mock(
        return_value={
            "external_join_url": "https://example/join",
            "numeric_meeting_code": "123456789",
        }
    )
    wecom.send_text.return_value = False
    scheduler = Scheduler(repository, wecom)

    result = await scheduler.create(
        "resource-owner",
        ReservationCreate(
            title="创建人主持会议",
            start_at=START,
            duration_minutes=60,
        ),
        "request-key-123456789",
    )

    assert result["status"] == "CREATED"
    wecom.update_meeting.assert_not_awaited()
    wecom.cancel_meeting.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_returns_recommendations_when_resource_busy():
    repository = FakeRepository()
    wecom = AsyncMock()
    wecom.get_user_meeting_ids.return_value = ["existing-meeting"]
    wecom.get_meeting_info.return_value = {"status": 1}
    scheduler = Scheduler(repository, wecom)

    with pytest.raises(ResourceUnavailable) as captured:
        await scheduler.create(
            "requester",
            ReservationCreate(
                title="项目评审",
                start_at=START,
                duration_minutes=60,
            ),
            "request-key-123456789",
        )

    assert len(captured.value.recommendations) == 3
    wecom.create_meeting.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancelled_remote_meeting_does_not_block_resource():
    repository = FakeRepository()
    wecom = AsyncMock()
    wecom.get_user_meeting_ids.return_value = ["cancelled-meeting"]
    wecom.get_meeting_info.return_value = {"status": 4}
    scheduler = Scheduler(repository, wecom)

    assert not await scheduler.remote_busy(
        "resource-owner",
        START,
        START + timedelta(hours=1),
        10,
    )
