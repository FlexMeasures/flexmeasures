import pytest
from flask_login import current_user, logout_user
from flask_security.core import AnonymousUser
from flask import url_for

from flexmeasures.api.tests.utils import UserContext


def test_auth_token(app, client, setup_api_test_data):
    """Use an auth token to query an endpoint.
    (we test other endpoints using the api/conftest/requesting_user fixture,
     so they're already logged in via session)

    Note: The patched_check_token is now applied globally via the patch_check_token
    fixture in api/conftest.py, so no need to monkeypatch here.
    """
    with UserContext("test_admin_user@seita.nl") as admin:
        auth_token = admin.get_auth_token()
    assert isinstance(current_user, AnonymousUser)

    print("Getting assets ...")
    response = client.get(
        url_for("AssetAPI:index"), headers={"Authorization": auth_token}
    )
    print(response)
    assert response.status_code == 200
    logout_user()  # undo the login made by our patch during token auth
    assert response.json == []  # admin has no assets themselves


def _request_token(client, email: str, password: str = "testtest"):
    return client.post(
        url_for("flexmeasures_api.request_auth_token"),
        json={"email": email, "password": password},
    )


@pytest.mark.parametrize("two_factor", [False, True])
def test_request_auth_token_by_password_respects_two_factor(
    app, client, setup_api_test_data, monkeypatch, two_factor
):
    """With 2FA on, a password alone does not get a token (it would skip the second factor)."""
    monkeypatch.setitem(app.config, "SECURITY_TWO_FACTOR", two_factor)

    response = _request_token(client, "test_prosumer_user@seita.nl")

    if two_factor:
        assert response.status_code == 401, response.json
        assert "auth_token" not in response.json
        assert "two-factor" in response.json["errors"][0]
    else:
        assert response.status_code == 200, response.json
        assert response.json["auth_token"]


def test_request_auth_token_by_password_with_two_factor_can_be_allowed(
    app, client, setup_api_test_data, monkeypatch
):
    monkeypatch.setitem(app.config, "SECURITY_TWO_FACTOR", True)
    monkeypatch.setitem(app.config, "FLEXMEASURES_ALLOW_PASSWORD_TOKENS_WITH_2FA", True)

    response = _request_token(client, "test_prosumer_user@seita.nl")

    assert response.status_code == 200, response.json
    assert response.json["auth_token"]


def test_request_auth_token_with_two_factor_still_checks_the_password_first(
    app, client, setup_api_test_data, monkeypatch
):
    """The 2FA answer is only given for a correct password, so it does not confirm guesses."""
    monkeypatch.setitem(app.config, "SECURITY_TWO_FACTOR", True)

    response = _request_token(client, "test_prosumer_user@seita.nl", "wrong")

    assert response.status_code == 401
    assert response.json["errors"] == ["User password does not match."]
