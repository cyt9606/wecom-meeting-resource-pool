from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.models import ReservationCreate


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
