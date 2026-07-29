from datetime import datetime, timezone
from uuid import uuid4

from app.api import public_reservation, resource_unavailable_detail
from app.scheduler import ResourceUnavailable


def test_public_reservation_does_not_expose_resource_userid():
    now = datetime.now(timezone.utc)
    result = public_reservation(
        {
            "id": uuid4(),
            "status": "CREATED",
            "title": "评审",
            "description": "",
            "start_at": now,
            "end_at": now,
            "meetingid": "m1",
            "applicant_userid": "requester",
            "resource_display_name": "高级会议资源 01",
            "resource_userid": "resource-owner",
            "join_info_json": {},
            "settings_json": {
                "allow_external_user": False,
                "enable_waiting_room": True,
                "password": "2468",
            },
            "created_at": now,
            "updated_at": now,
        }
    )
    assert "resource_userid" not in result
    assert result["resource_display_name"] == "高级会议资源 01"
    assert result["host_userid"] == "requester"
    assert result["allow_external_user"] is False
    assert result["enable_waiting_room"] is True
    assert result["join_info"]["password"] == "2468"


def test_resource_unavailable_recommendations_are_json_serializable():
    now = datetime.now(timezone.utc)
    detail = resource_unavailable_detail(ResourceUnavailable([now]))

    assert detail == {
        "message": "所选时段的高级会议资源均已占用",
        "recommendations": [now.isoformat()],
    }
