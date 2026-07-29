from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.models import ReservationCreate, ReservationUpdate


def test_rejects_title_over_wecom_utf8_byte_limit():
    with pytest.raises(ValidationError, match="40 字节"):
        ReservationCreate(
            title="一二三四五六七八九十一二三四",
            start_at=datetime.now(timezone.utc) + timedelta(hours=1),
            duration_minutes=30,
        )


def test_rejects_duration_over_eight_hours():
    with pytest.raises(ValidationError):
        ReservationCreate(
            title="全天会议",
            start_at=datetime.now(timezone.utc) + timedelta(hours=1),
            duration_minutes=481,
        )


def test_accepts_optional_password_and_waiting_room():
    reservation = ReservationCreate(
        title="安全会议",
        start_at=datetime.now(timezone.utc) + timedelta(hours=1),
        duration_minutes=60,
        password=" 2468 ",
        enable_waiting_room=True,
    )

    assert reservation.password == "2468"
    assert reservation.enable_waiting_room is True


def test_rejects_invalid_meeting_password():
    with pytest.raises(ValidationError):
        ReservationCreate(
            title="安全会议",
            start_at=datetime.now(timezone.utc) + timedelta(hours=1),
            duration_minutes=60,
            password="12ab",
        )


def test_update_accepts_all_create_fields_and_password_removal():
    update = ReservationUpdate(
        title="新主题",
        start_at=datetime.now(timezone.utc) + timedelta(hours=2),
        duration_minutes=90,
        description="新说明",
        allow_external_user=False,
        password="",
        enable_waiting_room=True,
    )

    assert update.password is None
    assert "password" in update.model_fields_set
