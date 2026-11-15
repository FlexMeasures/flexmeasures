"""The cookies that keep a user logged in are not sent along with other sites' requests, and do not last a year."""

from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import pytest
from flask import url_for

from flexmeasures.utils.config_defaults import (
    DevelopmentConfig,
    ProductionConfig,
    StagingConfig,
)


def _login_cookies(client) -> dict[str, str]:
    """Log in with "remember me", and return the Set-Cookie headers by cookie name."""
    response = client.post(
        url_for("security.login"),
        data=dict(
            email="test_prosumer_user@seita.nl", password="testtest", remember="y"
        ),
    )
    assert response.status_code in (200, 302)
    return {
        header.split("=", 1)[0]: header
        for header in response.headers.getlist("Set-Cookie")
    }


@pytest.mark.parametrize("config", [ProductionConfig, StagingConfig])
def test_session_cookies_are_secure_in_deployed_environments(config):
    assert config.SESSION_COOKIE_SECURE is True
    assert config.REMEMBER_COOKIE_SECURE is True


def test_session_cookies_need_no_https_in_development():
    assert DevelopmentConfig.SESSION_COOKIE_SECURE is False
    assert DevelopmentConfig.REMEMBER_COOKIE_SECURE is False


def test_login_cookies_are_same_site_and_short_lived(client, setup_roles_users, app):
    cookies = _login_cookies(client)
    client.post(url_for("security.logout"))

    for name in ("session", "remember_token"):
        assert name in cookies, cookies.keys()
        assert "SameSite=Lax" in cookies[name], cookies[name]
        assert "HttpOnly" in cookies[name], cookies[name]

    expires = parsedate_to_datetime(
        cookies["remember_token"].split("Expires=", 1)[1].split(";", 1)[0]
    )
    assert expires - datetime.now(timezone.utc) < timedelta(days=15)


def test_login_cookies_are_secure_with_the_deployed_settings(
    client, setup_roles_users, app, monkeypatch
):
    monkeypatch.setitem(app.config, "SESSION_COOKIE_SECURE", True)
    monkeypatch.setitem(app.config, "REMEMBER_COOKIE_SECURE", True)
    cookies = _login_cookies(client)
    client.post(url_for("security.logout"))

    for name in ("session", "remember_token"):
        assert "Secure" in cookies[name], cookies[name]
