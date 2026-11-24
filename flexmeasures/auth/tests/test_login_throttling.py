"""Failed attempts to authenticate are limited per email address (and client address), and password recovery requests per email address."""

import pytest
from flask import Flask, request, session, url_for
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
        app.config, "FLEXMEASURES_AUTHENTICATION_FAILURE_CEILING", "5 per hour"
    )
    monkeypatch.setitem(
        app.config, "FLEXMEASURES_PASSWORD_RECOVERY_LIMIT", "2 per hour"
    )
    yield
    limiter.reset()
    logout_user()


ATTACKER = "203.0.113.66"
OWNER = "198.51.100.7"


def form_login(client, email, password, address="127.0.0.1"):
    return client.post(
        url_for("security.login"),
        data=dict(email=email, password=password),
        environ_base={"REMOTE_ADDR": address},
    )


def request_token(client, email, password, address="127.0.0.1"):
    return client.post(
        url_for("flexmeasures_api.request_auth_token"),
        json=dict(email=email, password=password),
        environ_base={"REMOTE_ADDR": address},
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
    """Two-factor codes are counted against the email address of the user who is logging in."""
    from werkzeug.routing import Rule

    from flexmeasures.auth.login_throttling import refuse_attempts_beyond_limit

    user = db.session.execute(select(User).filter_by(email=EMAIL)).scalar_one()
    answers = []
    for _ in range(4):
        # SECURITY_TWO_FACTOR is off in tests, so we route a request to the 2FA endpoint by hand
        with app.test_request_context(
            "/tf-validate",
            method="POST",
            data={},
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        ):
            request.url_rule = Rule(
                "/tf-validate", endpoint="security.two_factor_token_validation"
            )
            session["tf_user_id"] = user.fs_uniquifier
            answers.append(refuse_attempts_beyond_limit())
    assert answers[:3] == [None, None, None]
    assert answers[3].status_code == 429

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


def test_guessing_from_one_address_does_not_lock_the_owner_out(
    app, client, setup_roles_users, low_limits
):
    """Someone who knows the email address can use up the attempts from their own address only."""
    for _ in range(3):
        assert not logged_in(form_login(client, EMAIL, "wrong-password", ATTACKER))
    assert form_login(client, EMAIL, PASSWORD, ATTACKER).status_code == 429
    assert request_token(client, EMAIL, PASSWORD, ATTACKER).status_code == 429

    # The owner, and a script fetching tokens, from another address still get in
    response = request_token(client, EMAIL, PASSWORD, OWNER)
    assert response.status_code == 200 and "auth_token" in response.json
    assert logged_in(form_login(client, EMAIL, PASSWORD, OWNER))


def test_guessing_from_many_addresses_hits_a_ceiling(
    app, client, setup_roles_users, low_limits
):
    """Per email address, all client addresses together get a higher ceiling (5 here)."""
    for address in ("203.0.113.1", "203.0.113.1", "203.0.113.2", "203.0.113.2"):
        assert (
            request_token(client, EMAIL, "wrong-password", address).status_code == 401
        )
    assert (
        request_token(client, EMAIL, "wrong-password", "203.0.113.3").status_code == 401
    )
    assert request_token(client, EMAIL, PASSWORD, OWNER).status_code == 429


def test_unknown_email_addresses_are_counted_alike(
    app, client, setup_roles_users, low_limits
):
    """The 429 does not tell whether an account exists: unknown addresses are counted the same way."""
    for email in (EMAIL, "nobody@seita.nl"):
        for _ in range(3):
            assert not logged_in(form_login(client, email, "wrong-password"))
        assert form_login(client, email, "wrong-password").status_code == 429
        assert request_token(client, email, "wrong-password").status_code == 429
        # Case and surrounding spaces do not make it a different address
        assert form_login(client, f" {email.upper()} ", "x").status_code == 429


def test_successful_token_requests_are_not_held_against_the_user(
    app, client, setup_roles_users, low_limits
):
    """Attempts are counted before the password is checked, and cleared again when a token is issued."""
    for _ in range(6):
        response = request_token(client, EMAIL, PASSWORD)
        assert response.status_code == 200 and "auth_token" in response.json


def test_concurrent_attempts_cannot_exceed_the_limit(
    app, client, setup_roles_users, low_limits, monkeypatch
):
    """An attempt counts from the moment it arrives, not once its password turned out wrong.

    We let a second attempt arrive while the first one's password is being checked (as concurrent requests would).
    """
    import flexmeasures.api as api_module

    monkeypatch.setitem(
        app.config, "FLEXMEASURES_AUTHENTICATION_FAILURE_LIMIT", "1 per 15 minutes"
    )
    verify_password = api_module.verify_password
    concurrent_answers = []
    first_check = [True]

    def verify_password_while_another_attempt_arrives(password, password_hash):
        if first_check[0]:
            first_check[0] = False
            concurrent_answers.append(
                request_token(app.test_client(), EMAIL, "another-guess").status_code
            )
        return verify_password(password, password_hash)

    monkeypatch.setattr(
        api_module, "verify_password", verify_password_while_another_attempt_arrives
    )
    assert request_token(client, EMAIL, "wrong-password").status_code == 401
    assert concurrent_answers == [429]


@pytest.mark.parametrize(
    "trusted_proxies, expected_address", [(0, "127.0.0.1"), (1, "192.0.2.9")]
)
def test_client_address_behind_trusted_proxies(trusted_proxies, expected_address):
    """With FLEXMEASURES_TRUSTED_PROXIES, the client address comes from the proxies' X-Forwarded-For entries."""
    from flexmeasures.utils.app_utils import trust_proxies

    proxied_app = Flask("proxied")
    proxied_app.config["FLEXMEASURES_TRUSTED_PROXIES"] = trusted_proxies
    trust_proxies(proxied_app)
    proxied_app.add_url_rule("/", "address", lambda: request.remote_addr)

    response = proxied_app.test_client().get(
        "/", headers={"X-Forwarded-For": "10.6.6.6, 192.0.2.9"}
    )
    assert response.text == expected_address
