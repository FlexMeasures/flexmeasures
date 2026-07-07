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
