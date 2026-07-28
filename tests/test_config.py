import pytest
from pydantic import ValidationError

from app.config import Settings


BASE = {
    "APP_ENV": "test",
    "APP_BASE_URL": "http://meeting.example.com:13333/",
    "SESSION_SECRET": "x" * 32,
    "DATABASE_URL": "postgresql://user:pass@localhost/db",
    "WECOM_CORP_ID": "corp",
    "WECOM_APP_SECRET": "secret",
    "WECOM_MEETING_RESOURCE_USERIDS": "resource-one,resource-two",
}


def test_parses_resources_and_normalizes_base_url():
    settings = Settings(**BASE)
    assert settings.APP_BASE_URL == "http://meeting.example.com:13333"
    assert settings.WECOM_MEETING_RESOURCE_USERIDS == [
        "resource-one",
        "resource-two",
    ]


def test_production_rejects_test_auth():
    with pytest.raises(ValidationError):
        Settings(**{**BASE, "APP_ENV": "production", "ALLOW_TEST_AUTH": True})


def test_reads_csv_lists_from_environment_file(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "APP_ENV=test",
                "APP_BASE_URL=http://meeting.example.com",
                f"SESSION_SECRET={'x' * 32}",
                "DATABASE_URL=postgresql:///meeting_pool",
                "WECOM_CORP_ID=corp",
                "WECOM_APP_SECRET=secret",
                "WECOM_MEETING_RESOURCE_USERIDS=resource-one,resource-two",
                "WECOM_ADMIN_USERIDS=admin-one",
            ]
        ),
        encoding="utf-8",
    )
    settings = Settings(_env_file=env_file)
    assert settings.WECOM_MEETING_RESOURCE_USERIDS == [
        "resource-one",
        "resource-two",
    ]
    assert settings.WECOM_ADMIN_USERIDS == ["admin-one"]
