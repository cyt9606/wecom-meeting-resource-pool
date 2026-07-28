from app.access_control import is_public_path, is_wecom_user_agent


def test_accepts_enterprise_wechat_client_user_agents():
    assert is_wecom_user_agent(
        "Mozilla/5.0 MicroMessenger/8.0 wxwork/4.1.36"
    )
    assert is_wecom_user_agent("Mozilla/5.0 WXWORK/5.0")


def test_rejects_normal_browsers_and_consumer_wechat():
    assert not is_wecom_user_agent("Mozilla/5.0 Chrome/130.0")
    assert not is_wecom_user_agent("Mozilla/5.0 MicroMessenger/8.0")
    assert not is_wecom_user_agent(None)


def test_only_health_endpoint_is_public():
    assert is_public_path("/health")
    assert not is_public_path("/")
    assert not is_public_path("/api/v1/me")
    assert not is_public_path("/WW_verify_untrusted.txt")
