"""A token needs the user's password, also from a logged-in session, and is not issued to deactivated users."""

import pytest
from flask import url_for
from flask_login import logout_user

from flexmeasures.data.services.users import find_user_by_email

EMAIL = "test_prosumer_user@seita.nl"
PASSWORD = "testtest"


@pytest.fixture(autouse=True)
def logged_out():
    yield
    logout_user()


def request_token(client, **payload):
    return client.post(url_for("flexmeasures_api.request_auth_token"), json=payload)


@pytest.mark.parametrize(
    "password, expected_status",
    [(None, 422), ("not-the-password", 401), (PASSWORD, 200)],
)
def test_session_needs_the_password_for_a_token(
    app, client, setup_api_test_data, password, expected_status
):
    response = client.post(
        url_for("security.login"), data=dict(email=EMAIL, password=PASSWORD)
    )
    assert response.status_code == 302  # logged in

    payload = dict(email=EMAIL)
    if password is not None:
        payload["password"] = password
    response = request_token(client, **payload)

    assert response.status_code == expected_status, response.json
    assert ("auth_token" in response.json) == (expected_status == 200)


def test_deactivated_user_gets_no_token(app, db, client, setup_api_test_data):
    user = find_user_by_email(EMAIL)
    user.active = False
    db.session.flush()
    try:
        response = request_token(client, email=EMAIL, password=PASSWORD)
        assert response.status_code == 401
        assert "auth_token" not in response.json
        assert "user_id" not in response.json
    finally:
        user.active = True
        db.session.flush()
