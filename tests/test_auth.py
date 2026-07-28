from types import SimpleNamespace

from app.auth import current_user, safe_next


class FakeRepository:
    def __init__(self, admins: set[str]):
        self.admins = {userid.lower() for userid in admins}

    def is_admin(self, userid: str) -> bool:
        return userid.lower() in self.admins


def test_safe_next_rejects_external_redirect():
    assert safe_next("https://evil.example/steal") == "/"
    assert safe_next("//evil.example/steal") == "/"


def test_safe_next_accepts_local_path():
    assert safe_next("/reservations/123") == "/reservations/123"


def test_current_user_reads_admin_role_from_repository():
    request = SimpleNamespace(
        session={"userid": "AdminUser"},
        app=SimpleNamespace(
            state=SimpleNamespace(repository=FakeRepository({"adminuser"}))
        ),
    )

    user = current_user(request)

    assert user.userid == "AdminUser"
    assert user.is_admin is True


def test_current_user_reflects_admin_removal_immediately():
    repository = FakeRepository({"AdminUser"})
    request = SimpleNamespace(
        session={"userid": "AdminUser"},
        app=SimpleNamespace(state=SimpleNamespace(repository=repository)),
    )
    assert current_user(request).is_admin is True

    repository.admins.clear()

    assert current_user(request).is_admin is False
