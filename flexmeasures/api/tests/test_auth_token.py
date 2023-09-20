from flask_login import current_user, login_user, logout_user
from flask_security.core import AnonymousUser
from flask_security.proxies import _security
from flask_security import decorators as fs_decorators
from flask_principal import Identity, identity_changed
from flask import url_for, current_app, request

from flexmeasures.api.tests.utils import UserContext


def patched_check_token() -> bool:
    """
    The _check_token function in Flask-Security is successfully getting the user,
    but it fails to stick with flask_login.
    This happens only when testing, so our test setup might not be 100% compatible
    with Flask >2.2 ecosystem.

    See for details:
    https://github.com/FlexMeasures/flexmeasures/pull/838#discussion_r1321692937
    https://github.com/Flask-Middleware/flask-security/issues/834
    """
    user = _security.login_manager.request_callback(request)
    if user and user.is_authenticated:
        app = current_app._get_current_object()
        identity_changed.send(app, identity=Identity(user.fs_uniquifier))

        login_user(user)  # THIS LINE ADDED BY US
        return True

    return False


def test_auth_token(monkeypatch, app, client, setup_api_test_data):
    """Use an auth token to query an endpoint.
    (we test other endpoints using the api/conftest/requesting_user fixture,
     so they're already logged in via session)
    """
    with UserContext("test_admin_user@seita.nl") as admin:
        auth_token = admin.get_auth_token()
    assert isinstance(current_user, AnonymousUser)

    monkeypatch.setattr(fs_decorators, "_check_token", patched_check_token)

    print("Getting assets ...")
    response = client.get(
        url_for("AssetAPI:index"), headers={"Authorization": auth_token}
    )
    print(response)
    assert response.status_code == 200
    logout_user()  # undo the login made by our patch during token auth
    assert response.json == []  # admin has no assets themselves
