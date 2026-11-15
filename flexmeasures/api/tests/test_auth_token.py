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


@pytest.mark.parametrize("url", ["/api/v3_0/assets", "/assets"])
def test_auth_token_in_url_is_refused(app, client, setup_api_test_data, url):
    """Tokens in the URL query end up in logs, browser history and Referer headers, so they are refused, also on UI pages.

    The same token in the Authorization header works (see test_auth_token).
    """
    with UserContext("test_admin_user@seita.nl") as admin:
        auth_token = admin.get_auth_token()

    response = client.get(url, query_string={"auth_token": auth_token})
    logout_user()  # undo any login made by our patch during token auth
    assert response.status_code == 400, response.status_code
    assert auth_token not in response.get_data(as_text=True)
