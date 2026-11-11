"""Exercise token lifecycle endpoints with real Flask-Security authentication."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
import time

import pytest
from flask import g, url_for
from sqlalchemy import select

from flexmeasures.data.models.user import User


@pytest.fixture(autouse=True)
def patch_check_token():
    """Use real token validation, including expiry and inactive-user checks."""


@pytest.fixture
def token_user(fresh_db, setup_roles_users_fresh_db):
    user = fresh_db.session.scalar(
        select(User).filter_by(email="test_admin_user@seita.nl")
    )
    fresh_db.session.commit()
    return user


def login(client, **kwargs):
    if "include_refresh_token" in kwargs:
        kwargs["include-refresh-token"] = kwargs.pop("include_refresh_token")
    return client.post(
        "/api/requestAuthToken",
        json={"email": "test_admin_user@seita.nl", "password": "testtest", **kwargs},
    )


def refresh(client, token):
    return client.post("/api/refreshAuthToken", json={"refresh-token": token})


def clear_auth():
    # The session-scoped app context otherwise caches authentication across requests.
    for key in ("_login_user", "fs_authn_via", "fs_paa", "csrf_valid"):
        g.pop(key, None)


def assert_pair(response, user_id):
    assert response.status_code == 200, response.json
    assert {
        "auth_token",
        "user_id",
        "refresh-token",
        "expires-in",
    } <= response.json.keys()
    assert not {"refresh_token", "expires_in"} & response.json.keys()
    assert response.json["user_id"] == user_id
    assert isinstance(response.json["auth_token"], str)
    assert isinstance(response.json["refresh-token"], str)
    assert response.json["auth_token"] != response.json["refresh-token"]
    assert isinstance(response.json["expires-in"], int)
    assert response.json["expires-in"] > 0
    assert "no-store" in response.headers["Cache-Control"]
    return response.json


@pytest.mark.parametrize("options", [{}, {"include_refresh_token": False}])
def test_legacy_token_response(client, token_user, options):
    response = login(client, **options)
    assert response.status_code == 200
    assert set(response.json) == {"auth_token", "user_id", "status"}
    assert response.json["user_id"] == token_user.id
    clear_auth()
    response = client.get(
        url_for("AssetAPI:index"),
        headers={"Authorization": response.json["auth_token"]},
    )
    assert response.status_code == 200


def test_issue_and_rotate_tokens(client, token_user):
    pair = assert_pair(login(client, include_refresh_token=True), token_user.id)
    rotated = assert_pair(refresh(client, pair["refresh-token"]), token_user.id)
    assert rotated["refresh-token"] != pair["refresh-token"]
    clear_auth()
    assert (
        client.get(
            url_for("AssetAPI:index"), headers={"Authorization": rotated["auth_token"]}
        ).status_code
        == 200
    )


def test_refresh_token_cannot_authenticate_api_request(client, token_user):
    pair = assert_pair(login(client, include_refresh_token=True), token_user.id)
    clear_auth()
    assert (
        client.get(
            url_for("AssetAPI:index"), headers={"Authorization": pair["refresh-token"]}
        ).status_code
        == 401
    )


def test_access_token_cannot_be_refreshed(client, token_user):
    pair = assert_pair(login(client, include_refresh_token=True), token_user.id)
    assert refresh(client, pair["auth_token"]).status_code == 401


def test_reuse_revokes_rotated_token_family(client, token_user):
    pair = assert_pair(login(client, include_refresh_token=True), token_user.id)
    rotated = assert_pair(refresh(client, pair["refresh-token"]), token_user.id)
    assert refresh(client, pair["refresh-token"]).status_code == 401
    assert refresh(client, rotated["refresh-token"]).status_code == 401


def test_revoke_refresh_token(client, token_user):
    pair = assert_pair(login(client, include_refresh_token=True), token_user.id)
    response = client.post(
        "/api/revokeRefreshToken", json={"refresh-token": pair["refresh-token"]}
    )
    assert response.status_code == 200
    assert refresh(client, pair["refresh-token"]).status_code == 401


@pytest.mark.parametrize("include_refresh_token", [False, True])
def test_disabled_user_cannot_obtain_tokens(
    client, fresh_db, token_user, include_refresh_token
):
    token_user.active = False
    fresh_db.session.commit()
    options = {"include_refresh_token": True} if include_refresh_token else {}
    assert login(client, **options).status_code == 401


def test_disabled_user_cannot_refresh(client, fresh_db, token_user):
    pair = assert_pair(login(client, include_refresh_token=True), token_user.id)
    token_user.active = False
    fresh_db.session.commit()
    assert refresh(client, pair["refresh-token"]).status_code == 401
    token_user.active = True
    fresh_db.session.commit()
    assert refresh(client, pair["refresh-token"]).status_code == 401


@pytest.mark.parametrize("path", ["/api/refreshAuthToken", "/api/revokeRefreshToken"])
@pytest.mark.parametrize(
    "payload", [{}, {"refresh-token": None}, {"refresh-token": 12}]
)
def test_malformed_refresh_requests(client, token_user, path, payload):
    assert client.post(path, json=payload).status_code in (400, 422)


@pytest.mark.parametrize("path", ["/api/refreshAuthToken", "/api/revokeRefreshToken"])
def test_invalid_refresh_token(client, token_user, path):
    assert client.post(path, json={"refresh-token": "invalid"}).status_code == 401


@pytest.fixture
def token_clock(app, monkeypatch):
    """Advance both token signatures and refresh tracker clocks together."""
    security = app.extensions["security"]
    initial = security.datetime_factory()
    wall_time = time.time()

    def advance(seconds):
        monkeypatch.setattr(
            security, "datetime_factory", lambda: initial + timedelta(seconds=seconds)
        )
        monkeypatch.setattr(time, "time", lambda: wall_time + seconds)

    return advance


def test_expired_access_token_can_be_refreshed(
    app, client, token_user, token_clock, monkeypatch
):
    monkeypatch.setitem(app.config, "SECURITY_TOKEN_MAX_AGE", timedelta(seconds=5))
    pair = assert_pair(login(client, include_refresh_token=True), token_user.id)
    # Remaining lifetime is rounded down to avoid overstating validity.
    assert 0 < pair["expires-in"] <= 5
    token_clock(10)
    clear_auth()
    assert (
        client.get(
            url_for("AssetAPI:index"), headers={"Authorization": pair["auth_token"]}
        ).status_code
        == 401
    )
    assert_pair(refresh(client, pair["refresh-token"]), token_user.id)


def test_refresh_idle_expiry(app, client, token_user, token_clock, monkeypatch):
    monkeypatch.setitem(
        app.config, "SECURITY_REFRESH_TOKEN_MAX_IDLE", timedelta(seconds=10)
    )
    pair = assert_pair(login(client, include_refresh_token=True), token_user.id)
    token_clock(11)
    assert refresh(client, pair["refresh-token"]).status_code == 401


def test_rotation_preserves_absolute_expiry(
    app, client, token_user, token_clock, monkeypatch
):
    monkeypatch.setitem(
        app.config, "SECURITY_REFRESH_TOKEN_MAX_AGE", timedelta(seconds=20)
    )
    monkeypatch.setitem(
        app.config, "SECURITY_REFRESH_TOKEN_MAX_IDLE", timedelta(seconds=15)
    )
    pair = assert_pair(login(client, include_refresh_token=True), token_user.id)
    token_clock(10)
    pair = assert_pair(refresh(client, pair["refresh-token"]), token_user.id)
    token_clock(21)
    assert refresh(client, pair["refresh-token"]).status_code == 401


def test_independent_login_has_independent_token_family(client, token_user):
    first = assert_pair(login(client, include_refresh_token=True), token_user.id)
    second = assert_pair(login(client, include_refresh_token=True), token_user.id)
    assert first["refresh-token"] != second["refresh-token"]
    client.post(
        "/api/revokeRefreshToken", json={"refresh-token": first["refresh-token"]}
    )
    assert_pair(refresh(client, second["refresh-token"]), token_user.id)


def test_wrong_password_cannot_obtain_refresh_token(client, fresh_db, token_user):
    response = login(client, include_refresh_token=True, password="incorrect")
    assert response.status_code == 401
    assert "refresh-token" not in response.json
    fresh_db.session.refresh(token_user)
    assert not token_user.refresh_trackers


def test_changed_token_identity_revokes_refresh(client, fresh_db, token_user):
    pair = assert_pair(login(client, include_refresh_token=True), token_user.id)
    token_user.fs_uniquifier = "changed-token-identity"
    fresh_db.session.commit()
    assert refresh(client, pair["refresh-token"]).status_code == 401


def test_concurrent_refresh_revokes_family(app, client, token_user):
    """Only one racing refresh succeeds, and replay revokes its replacement."""
    pair = assert_pair(login(client, include_refresh_token=True), token_user.id)
    barrier = Barrier(2)

    def exchange():
        with app.app_context(), app.test_client() as concurrent_client:
            barrier.wait(timeout=10)
            response = refresh(concurrent_client, pair["refresh-token"])
            return response.status_code, response.json

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(exchange) for _ in range(2)]
        responses = [future.result(timeout=20) for future in futures]
    assert sorted(status for status, _ in responses) == [200, 401]
    replacement = next(
        body["refresh-token"] for status, body in responses if status == 200
    )
    assert refresh(client, replacement).status_code == 401


@pytest.mark.parametrize("change", ["password", "deactivate"])
def test_security_change_revokes_without_refresh_attempt(
    client, fresh_db, token_user, change
):
    pair = assert_pair(login(client, include_refresh_token=True), token_user.id)
    if change == "password":
        token_user.password = "changed-password-hash"
    else:
        token_user.active = False
    fresh_db.session.commit()
    if change == "deactivate":
        token_user.active = True
        fresh_db.session.commit()
    assert refresh(client, pair["refresh-token"]).status_code == 401


def test_per_token_expiry_limits_reported_lifetime(
    app, client, token_user, monkeypatch
):
    monkeypatch.setitem(
        app.config, "SECURITY_TOKEN_EXPIRE_TIMESTAMP", lambda user: time.time() + 30
    )
    pair = assert_pair(login(client, include_refresh_token=True), token_user.id)
    assert 0 < pair["expires-in"] <= 30


def test_unlimited_access_token_lifetime(app, client, token_user, monkeypatch):
    monkeypatch.setitem(app.config, "SECURITY_TOKEN_MAX_AGE", timedelta(0))
    monkeypatch.setitem(app.config, "SECURITY_TOKEN_EXPIRE_TIMESTAMP", lambda user: 0)
    response = login(client, include_refresh_token=True)
    assert response.status_code == 200
    assert response.json["expires-in"] is None


def test_revocation_at_same_instant(client, token_user, token_clock):
    """Revocation is immediate, even when two requests share a clock timestamp."""
    token_clock(0)
    pair = assert_pair(login(client, include_refresh_token=True), token_user.id)
    response = client.post(
        "/api/revokeRefreshToken", json={"refresh-token": pair["refresh-token"]}
    )
    assert response.status_code == 200
    assert response.json["revoked"] is True
    assert refresh(client, pair["refresh-token"]).status_code == 401


def test_session_cannot_replace_password_for_refresh_issuance(client, token_user):
    with client.session_transaction() as session:
        session["_user_id"] = token_user.get_id()
        session["_fresh"] = True
    clear_auth()
    # Preserve the existing signed-in access-token flow, but require the password
    # before issuing a new long-lived refresh credential.
    assert login(client, password="incorrect").status_code == 200
    clear_auth()
    response = login(client, password="incorrect", include_refresh_token=True)
    assert response.status_code == 401
    assert "refresh-token" not in response.json
