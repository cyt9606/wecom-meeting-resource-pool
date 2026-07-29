from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator


class ReservationStatus(str, Enum):
    HELD = "HELD"
    CREATING = "CREATING"
    CREATED = "CREATED"
    UPDATING = "UPDATING"
    CANCELLING = "CANCELLING"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"
    RECONCILING = "RECONCILING"


class ReservationCreate(BaseModel):
    title: str = Field(min_length=1, max_length=20)
    start_at: datetime
    duration_minutes: int = Field(ge=5, le=480)
    description: str = Field(default="", max_length=500)
    allow_external_user: bool = True
    password: str | None = Field(
        default=None,
        pattern=r"^[0-9]{4,6}$",
    )
    enable_waiting_room: bool = False

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("会议主题不能为空")
        if len(value.encode("utf-8")) > 40:
            raise ValueError("会议主题不能超过 40 字节（中文通常不超过 13 个字）")
        return value

    @field_validator("start_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("start_at 必须包含时区")
        return value.astimezone(timezone.utc)

    @field_validator("password", mode="before")
    @classmethod
    def clean_password(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @property
    def end_at(self) -> datetime:
        return self.start_at + timedelta(minutes=self.duration_minutes)


class ReservationUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=20)
    start_at: datetime | None = None
    duration_minutes: int | None = Field(default=None, ge=5, le=480)
    description: str | None = Field(default=None, max_length=500)
    allow_external_user: bool | None = None
    password: str | None = Field(default=None, pattern=r"^[0-9]{4,6}$")
    enable_waiting_room: bool | None = None

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("会议主题不能为空")
        if len(value.encode("utf-8")) > 40:
            raise ValueError("会议主题不能超过 40 字节（中文通常不超过 13 个字）")
        return value

    @field_validator("start_at")
    @classmethod
    def normalize_timezone(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("start_at 必须包含时区")
        return value.astimezone(timezone.utc)

    @field_validator("password", mode="before")
    @classmethod
    def clean_password(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @model_validator(mode="after")
    def time_fields_together(self) -> "ReservationUpdate":
        if (self.start_at is None) != (self.duration_minutes is None):
            raise ValueError("修改时间时必须同时提交 start_at 和 duration_minutes")
        if not self.model_fields_set:
            raise ValueError("没有可修改的字段")
        return self


def validate_policy(
    request: ReservationCreate,
    *,
    now: datetime,
    min_lead_minutes: int,
    max_duration_minutes: int,
    max_advance_days: int,
) -> None:
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)
    if request.start_at < now + timedelta(minutes=min_lead_minutes):
        raise ValueError(f"会议至少需要提前 {min_lead_minutes} 分钟申请")
    if request.duration_minutes > max_duration_minutes:
        raise ValueError(f"会议时长不能超过 {max_duration_minutes} 分钟")
    if request.start_at > now + timedelta(days=max_advance_days):
        raise ValueError(f"最多只能提前 {max_advance_days} 天预约")


def busy_bounds(
    start_at: datetime, end_at: datetime, buffer_minutes: int
) -> tuple[datetime, datetime]:
    buffer = timedelta(minutes=buffer_minutes)
    return start_at - buffer, end_at + buffer


def overlaps(
    left_start: datetime,
    left_end: datetime,
    right_start: datetime,
    right_end: datetime,
) -> bool:
    """Half-open interval overlap: [start, end)."""
    return left_start < right_end and right_start < left_end
