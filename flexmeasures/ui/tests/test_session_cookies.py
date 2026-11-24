"""The cookies that keep a user logged in are not sent along with other sites' requests, and do not last a year."""

from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import pytest
from flask import url_for

from flask import Flask

from flexmeasures.utils.config_defaults import (
    DevelopmentConfig,
    ProductionConfig,
    StagingConfig,
)
from flexmeasures.utils.config_utils import resolve_cookie_security


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


def _resolved_cookie_settings(config, **host_settings) -> tuple:
    app = Flask(__name__)
    app.config.from_object(config)
    app.config.update(host_settings)
    resolve_cookie_security(app)
    return app.config["SESSION_COOKIE_SECURE"], app.config["REMEMBER_COOKIE_SECURE"]


@pytest.mark.parametrize("config", [ProductionConfig, StagingConfig, DevelopmentConfig])
def test_session_cookies_are_secure_when_https_is_forced(config):
    """Secure cookies follow FLEXMEASURES_FORCE_HTTPS, in every environment."""
    assert _resolved_cookie_settings(config, FLEXMEASURES_FORCE_HTTPS=True) == (
        True,
        True,
    )
    assert _resolved_cookie_settings(config, FLEXMEASURES_FORCE_HTTPS=False) == (
        False,
        False,
    )
    assert _resolved_cookie_settings(config) == (False, False)


def test_session_cookie_settings_of_the_host_are_kept():
    assert _resolved_cookie_settings(
        ProductionConfig,
        FLEXMEASURES_FORCE_HTTPS=True,
        SESSION_COOKIE_SECURE=False,
    ) == (False, True)
    assert _resolved_cookie_settings(
        ProductionConfig,
        FLEXMEASURES_FORCE_HTTPS=False,
        REMEMBER_COOKIE_SECURE=True,
    ) == (False, True)


def test_session_cookie_security_is_resolved_at_startup(app):
    """The app gets a definite value (the test app does not force HTTPS)."""
    assert app.config["SESSION_COOKIE_SECURE"] is False
    assert app.config["REMEMBER_COOKIE_SECURE"] is False


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
