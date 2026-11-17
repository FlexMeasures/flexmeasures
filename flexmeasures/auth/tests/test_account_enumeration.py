"""Login, token and password recovery answers do not tell whether a user with some email address exists."""

import re

import pytest
from flask import url_for
from flask_login import logout_user

KNOWN = "test_prosumer_user@seita.nl"
UNKNOWN = "nobody-at-all@seita.nl"


@pytest.fixture(autouse=True)
def logged_out():
    yield
    logout_user()


def visible_text(response) -> str:
    """The page's text without its tags and the email address we sent, which the form shows back."""
    text = re.sub(r"<[^>]+>", " ", response.get_data(as_text=True))
    text = text.replace(KNOWN, "<email>").replace(UNKNOWN, "<email>")
    text = re.sub(r'value="[^"]*"', "", text)
    return " ".join(text.split())


def test_token_endpoint_answers_unknown_email_like_wrong_password(
    app, client, setup_roles_users
):
    url = url_for("flexmeasures_api.request_auth_token")
    wrong_password = client.post(url, json=dict(email=KNOWN, password="wrong"))
    unknown_email = client.post(url, json=dict(email=UNKNOWN, password="wrong"))
    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json == unknown_email.json


def test_login_form_answers_unknown_email_like_wrong_password(
    app, client, setup_roles_users
):
    url = url_for("security.login")
    wrong_password = client.post(url, data=dict(email=KNOWN, password="wrong"))
    unknown_email = client.post(url, data=dict(email=UNKNOWN, password="wrong"))
    assert wrong_password.status_code == unknown_email.status_code
    assert visible_text(wrong_password) == visible_text(unknown_email)
    assert "does not exist" not in visible_text(unknown_email)


def test_password_recovery_answers_alike_for_every_email(
    app, client, setup_roles_users
):
    url = url_for("security.forgot_password")
    with app.mail.record_messages() as outbox:
        known = client.post(url, data=dict(email=KNOWN))
        unknown = client.post(url, data=dict(email=UNKNOWN))
    assert len(outbox) == 1  # only the known user gets instructions
    assert known.status_code == unknown.status_code == 200
    assert visible_text(known) == visible_text(unknown)
