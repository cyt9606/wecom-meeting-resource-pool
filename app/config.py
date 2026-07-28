from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8-sig",
        extra="ignore",
        case_sensitive=True,
    )

    APP_ENV: Literal["development", "test", "production"] = "production"
    APP_BASE_URL: str
    SESSION_SECRET: str = ""
    SESSION_SECRET_FILE: Path | None = None
    DATABASE_URL: str

    WECOM_CORP_ID: str
    WECOM_APP_SECRET: str
    WECOM_AGENT_ID: int | None = None
    WECOM_MEETING_RESOURCE_USERIDS: Annotated[list[str], NoDecode]
    WECOM_ADMIN_USERIDS: Annotated[list[str], NoDecode] = Field(
        default_factory=list
    )

    POLICY_BUFFER_MINUTES: int = Field(default=10, ge=0, le=120)
    POLICY_MIN_LEAD_MINUTES: int = Field(default=15, ge=0, le=1440)
    POLICY_MAX_DURATION_MINUTES: int = Field(default=480, ge=5, le=1440)
    POLICY_MAX_ADVANCE_DAYS: int = Field(default=90, ge=1, le=365)
    POLICY_MAX_PENDING_PER_USER: int = Field(default=10, ge=1, le=100)
    ALLOW_TEST_AUTH: bool = False
    REQUIRE_WECOM_CLIENT: bool = True

    @field_validator(
        "WECOM_MEETING_RESOURCE_USERIDS",
        "WECOM_ADMIN_USERIDS",
        mode="before",
    )
    @classmethod
    def parse_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @field_validator("APP_BASE_URL")
    @classmethod
    def normalize_base_url(cls, value: str) -> str:
        value = value.rstrip("/")
        if not value.startswith(("http://", "https://")):
            raise ValueError("APP_BASE_URL must start with http:// or https://")
        return value

    @model_validator(mode="after")
    def production_guards(self) -> "Settings":
        if not self.SESSION_SECRET and self.SESSION_SECRET_FILE:
            try:
                self.SESSION_SECRET = self.SESSION_SECRET_FILE.read_text(
                    encoding="utf-8"
                ).strip()
            except OSError as error:
                raise ValueError("cannot read SESSION_SECRET_FILE") from error
        if len(self.SESSION_SECRET) < 32:
            raise ValueError("SESSION_SECRET must contain at least 32 characters")
        if self.APP_ENV == "production" and self.ALLOW_TEST_AUTH:
            raise ValueError("ALLOW_TEST_AUTH cannot be enabled in production")
        if not self.WECOM_MEETING_RESOURCE_USERIDS:
            raise ValueError("at least one meeting resource userid is required")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
