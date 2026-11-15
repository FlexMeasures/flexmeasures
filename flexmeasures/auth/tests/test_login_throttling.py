"""Failed attempts to authenticate are limited per user, and password recovery requests per email address."""

import pytest
from flask import url_for
from flask_login import logout_user
from sqlalchemy import select

from flexmeasures.api.common.rate_limiting import limiter
from flexmeasures.data.models.user import User

EMAIL = "test_prosumer_user@seita.nl"
OTHER_EMAIL = "test_prosumer_user_2@seita.nl"
PASSWORD = "testtest"


@pytest.fixture
def low_limits(app, monkeypatch):
    limiter.reset()
    monkeypatch.setitem(
        app.config, "FLEXMEASURES_AUTHENTICATION_FAILURE_LIMIT", "3 per 15 minutes"
    )
    monkeypatch.setitem(
        app.config, "FLEXMEASURES_PASSWORD_RECOVERY_LIMIT", "2 per hour"
    )
    yield
    limiter.reset()
    logout_user()


def form_login(client, email, password):
    return client.post(
        url_for("security.login"), data=dict(email=email, password=password)
    )


def request_token(client, email, password):
    return client.post(
        url_for("flexmeasures_api.request_auth_token"),
        json=dict(email=email, password=password),
    )


def logged_in(response) -> bool:
    """Flask-Security redirects after a successful form login, and shows the form again otherwise."""
    return response.status_code == 302


def test_login_form_refuses_a_user_after_too_many_failed_attempts(
    app, client, setup_roles_users, low_limits
):
    for _ in range(3):
        response = form_login(client, EMAIL, "wrong-password")
        assert response.status_code == 200 and not logged_in(response)

    # Now even the right password is refused, without telling whether it was right
    response = form_login(client, EMAIL, PASSWORD)
    assert response.status_code == 429
    assert not logged_in(response)
    response = form_login(client, EMAIL, "wrong-password")
    assert response.status_code == 429

    # The token endpoint counts against the same user
    response = request_token(client, EMAIL, PASSWORD)
    assert response.status_code == 429
    assert "auth_token" not in (response.json or {})

    # Other users are not affected
    response = form_login(client, OTHER_EMAIL, PASSWORD)
    assert logged_in(response)


def test_failed_token_requests_count_against_the_user(
    app, client, setup_roles_users, low_limits
):
    for _ in range(3):
        response = request_token(client, EMAIL, "wrong-password")
        assert response.status_code == 401

    response = request_token(client, EMAIL, PASSWORD)
    assert response.status_code == 429
    response = form_login(client, EMAIL, PASSWORD)
    assert response.status_code == 429


def test_failed_two_factor_codes_count_against_the_user(
    app, db, client, setup_roles_users, low_limits
):
    """Flask-Security reports a wrong two-factor code as a failed authentication of that user."""
    user = db.session.execute(select(User).filter_by(email=EMAIL)).scalar_one()
    for _ in range(3):
        user.track_failed_authn("code", True)

    response = form_login(client, EMAIL, PASSWORD)
    assert response.status_code == 429


def test_a_successful_login_starts_the_count_afresh(
    app, client, setup_roles_users, low_limits
):
    for _ in range(2):
        form_login(client, EMAIL, "wrong-password")
    assert logged_in(form_login(client, EMAIL, PASSWORD))
    client.post(url_for("security.logout"))
    logout_user()

    for _ in range(2):
        form_login(client, EMAIL, "wrong-password")
    assert logged_in(form_login(client, EMAIL, PASSWORD))


@pytest.mark.parametrize("email", [EMAIL, "nobody@seita.nl"])
def test_password_recovery_requests_are_limited_per_email(
    app, client, setup_roles_users, low_limits, email
):
    for _ in range(2):
        response = client.post(
            url_for("security.forgot_password"), data=dict(email=email)
        )
        assert response.status_code != 429
    response = client.post(url_for("security.forgot_password"), data=dict(email=email))
    assert response.status_code == 429

    # Another address is not affected
    response = client.post(
        url_for("security.forgot_password"), data=dict(email=OTHER_EMAIL)
    )
    assert response.status_code != 429
