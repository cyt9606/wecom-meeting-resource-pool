from datetime import datetime, timedelta, timezone

import pytest

from app.models import ReservationCreate, busy_bounds, overlaps, validate_policy


NOW = datetime(2026, 7, 28, 8, 0, tzinfo=timezone.utc)


def test_half_open_adjacent_intervals_do_not_overlap():
    assert not overlaps(
        NOW,
        NOW + timedelta(hours=1),
        NOW + timedelta(hours=1),
        NOW + timedelta(hours=2),
    )


def test_buffer_expands_both_sides():
    start, end = busy_bounds(
        NOW, NOW + timedelta(hours=1), buffer_minutes=10
    )
    assert start == NOW - timedelta(minutes=10)
    assert end == NOW + timedelta(hours=1, minutes=10)


def test_policy_rejects_short_lead_time():
    request = ReservationCreate(
        title="项目评审",
        start_at=NOW + timedelta(minutes=5),
        duration_minutes=30,
    )
    with pytest.raises(ValueError, match="提前 15 分钟"):
        validate_policy(
            request,
            now=NOW,
            min_lead_minutes=15,
            max_duration_minutes=480,
            max_advance_days=90,
        )
