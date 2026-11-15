"""Authentication events are logged, without passwords or the addresses that were guessed."""

import logging

import pytest
from flask import url_for
from flask_login import logout_user
from sqlalchemy import select

from flexmeasures.data.models.user import User

EMAIL = "test_prosumer_user@seita.nl"
PASSWORD = "testtest"


@pytest.fixture
def auth_log(caplog):
    caplog.set_level(logging.INFO)
    yield caplog
    logout_user()


def events(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if "Authentication event:" in r.getMessage()]


def user_id(db, email=EMAIL) -> int:
    return db.session.execute(select(User.id).filter_by(email=email)).scalar_one()


def test_successful_login_is_logged(app, db, client, setup_roles_users, auth_log):
    response = client.post(
        url_for("security.login"), data=dict(email=EMAIL, password=PASSWORD)
    )
    assert response.status_code == 302
    [record] = events(auth_log)
    assert record.levelno == logging.INFO
    assert f"user {user_id(db)} logged in" in record.getMessage()

    client.post(url_for("security.logout"))
    assert f"user {user_id(db)} logged out" in events(auth_log)[-1].getMessage()


def test_failed_logins_are_logged(app, db, client, setup_roles_users, auth_log):
    client.post(
        url_for("security.login"), data=dict(email=EMAIL, password="secret-guess")
    )
    client.post(
        url_for("security.login"),
        data=dict(email="nobody-here@seita.nl", password="secret-guess"),
    )
    records = events(auth_log)
    assert len(records) == 2
    assert all(r.levelno == logging.WARNING for r in records)
    assert f"failed password for user {user_id(db)}" in records[0].getMessage()
    assert "unknown email address" in records[1].getMessage()
    for record in records:
        assert "secret-guess" not in record.getMessage()
        assert "nobody-here" not in record.getMessage()


def test_token_requests_are_logged(app, db, client, setup_roles_users, auth_log):
    url = url_for("flexmeasures_api.request_auth_token")
    assert (
        client.post(url, json=dict(email=EMAIL, password="secret-guess")).status_code
        == 401
    )
    # The status for an unknown email address is not what this test is about (it is 401 once that no longer differs from a wrong password)
    assert client.post(
        url, json=dict(email="nobody-here@seita.nl", password="x")
    ).status_code in (401, 404)
    response = client.post(url, json=dict(email=EMAIL, password=PASSWORD))
    assert response.status_code == 200
    messages = [r.getMessage() for r in events(auth_log)]
    assert len(messages) == 3
    assert f"failed password for user {user_id(db)}" in messages[0]
    assert "unknown email address" in messages[1]
    assert f"auth token issued to user {user_id(db)} (by password)" in messages[2]
    assert not any(response.json["auth_token"] in m for m in messages)


def test_two_factor_failures_are_logged(app, db, setup_roles_users, auth_log):
    user = db.session.execute(select(User).filter_by(email=EMAIL)).scalar_one()
    with app.test_request_context("/tf-validate", method="POST"):
        user.track_failed_authn("code", True)
    [record] = events(auth_log)
    assert f"failed two-factor code for user {user.id}" in record.getMessage()
