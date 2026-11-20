"""Exercise token lifecycle endpoints with real Flask-Security authentication."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, Event, local
import time
from uuid import uuid4

import pytest
from flask import g, url_for
from flask_security.tokens import new_refresh_tracker
from flask_security.utils import hash_password
from sqlalchemy import event, select

from flexmeasures.auth import tokens as auth_tokens
from flexmeasures.data.models.refresh_tokens import RefreshTokenTracker
from flexmeasures.data.models.user import User
from flexmeasures.data.services.users import delete_user


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


@pytest.mark.parametrize("value", ["not-a-boolean", None, [], {}])
def test_login_rejects_invalid_refresh_opt_in(client, token_user, value):
    response = login(client, include_refresh_token=value)
    assert response.status_code == 422


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


def test_revocation_is_committed_by_the_revoking_request(client, fresh_db, token_user):
    """The tests share one database session, so without the rollback here, the next request would commit a pending revocation."""
    pair = assert_pair(login(client, include_refresh_token=True), token_user.id)
    response = client.post(
        "/api/revokeRefreshToken", json={"refresh-token": pair["refresh-token"]}
    )
    assert response.status_code == 200
    fresh_db.session.rollback()
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


def test_user_disabled_outside_the_orm_cannot_refresh(client, fresh_db, token_user):
    """A bulk update skips the listener that revokes the families, so the exchange itself has to refuse an inactive user."""
    pair = assert_pair(login(client, include_refresh_token=True), token_user.id)
    fresh_db.session.execute(
        User.__table__.update().where(User.id == token_user.id).values(active=False)
    )
    fresh_db.session.commit()
    assert refresh(client, pair["refresh-token"]).status_code == 401


@pytest.mark.parametrize("families", ["not loaded", "loaded", "modified"])
def test_deleting_a_user_locks_the_user_before_the_families(
    app, client, fresh_db, token_user, families
):
    """Refreshing locks the user before the family, so deleting has to lock in that order as well, or the two can deadlock."""
    assert_pair(login(client, include_refresh_token=True), token_user.id)
    if families != "not loaded":
        assert len(token_user.refresh_trackers) == 1
    if families == "modified":
        token_user.refresh_trackers[0].name = "renamed"
    statements = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(fresh_db.engine, "before_cursor_execute", record)
    try:
        with app.test_request_context():
            delete_user(token_user)
            fresh_db.session.commit()
    finally:
        event.remove(fresh_db.engine, "before_cursor_execute", record)
    first_write = next(
        i for i, s in enumerate(statements) if s.startswith(("DELETE", "UPDATE"))
    )
    assert any(
        "FROM fm_user" in s and "FOR UPDATE" in s for s in statements[:first_write]
    )
    assert any(s.startswith("DELETE FROM fm_user") for s in statements)
    assert not fresh_db.session.scalars(select(RefreshTokenTracker)).all()


@pytest.mark.parametrize("path", ["/api/refreshAuthToken", "/api/revokeRefreshToken"])
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"refresh-token": None},
        {"refresh-token": 12},
        {"refresh-token": ""},
        {"refresh-token": "token", "refresh_token": "token"},
    ],
)
def test_malformed_refresh_requests(client, token_user, path, payload):
    assert client.post(path, json=payload).status_code == 422


@pytest.mark.parametrize("path", ["/api/refreshAuthToken", "/api/revokeRefreshToken"])
def test_refresh_request_with_unparsable_json(client, token_user, path):
    """Only JSON that cannot be parsed is a 400, whereas a body that fails validation is a 422."""
    response = client.post(path, data="{", content_type="application/json")
    assert response.status_code == 400


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


def test_login_cleans_dead_api_families_without_weakening_replay_detection(
    app, client, fresh_db, token_user, token_clock
):
    """Prune only this user's dead API families and retain live family history."""
    token_clock(0)
    first = assert_pair(login(client, include_refresh_token=True), token_user.id)
    rotated = assert_pair(refresh(client, first["refresh-token"]), token_user.id)
    expired = assert_pair(login(client, include_refresh_token=True), token_user.id)
    idle = assert_pair(login(client, include_refresh_token=True), token_user.id)
    revoked = assert_pair(login(client, include_refresh_token=True), token_user.id)
    security = app.extensions["security"]

    def family(pair):
        return security.refresh_token_serializer.loads(pair["refresh-token"])["family"]

    now = security.datetime_factory()
    trackers = {
        tracker.refresh_family: tracker
        for tracker in fresh_db.session.scalars(
            select(RefreshTokenTracker).where(
                RefreshTokenTracker.user_id == token_user.id
            )
        )
    }
    trackers[family(expired)].expires_at = now - timedelta(seconds=1)
    trackers[family(idle)].last_used_at = (
        now - app.config["SECURITY_REFRESH_TOKEN_MAX_IDLE"] - timedelta(seconds=1)
    )
    trackers[family(revoked)].revoked_at = now
    other_user = fresh_db.session.scalar(
        select(User).where(User.id != token_user.id).limit(1)
    )
    other_family = uuid4().hex
    browser_family = uuid4().hex
    for user_id, name, key in (
        (other_user.id, "api", other_family),
        (token_user.id, "browser", browser_family),
    ):
        fresh_db.session.add(
            RefreshTokenTracker(
                user_id=user_id,
                name=name,
                refresh_family=key,
                gen=1,
                expires_at=now + timedelta(days=1),
                last_used_at=now,
                revoked_at=now,
            )
        )
    fresh_db.session.commit()

    fresh = assert_pair(login(client, include_refresh_token=True), token_user.id)
    remaining = set(
        fresh_db.session.scalars(select(RefreshTokenTracker.refresh_family))
    )
    assert {family(first), family(fresh), other_family, browser_family} <= remaining
    assert not {family(expired), family(idle), family(revoked)} & remaining
    for pair in (expired, idle, revoked):
        assert refresh(client, pair["refresh-token"]).status_code == 401
    assert refresh(client, first["refresh-token"]).status_code == 401
    assert refresh(client, rotated["refresh-token"]).status_code == 401


def test_family_limit_rejects_new_login_without_revoking_existing_tokens(
    app, client, fresh_db, token_user, monkeypatch
):
    monkeypatch.setitem(app.config, "FLEXMEASURES_REFRESH_TOKEN_FAMILY_LIMIT", 2)
    first = assert_pair(login(client, include_refresh_token=True), token_user.id)
    second = assert_pair(login(client, include_refresh_token=True), token_user.id)
    now = app.extensions["security"].datetime_factory()
    stale = RefreshTokenTracker(
        user_id=token_user.id,
        name="api",
        refresh_family=uuid4().hex,
        gen=1,
        expires_at=now + timedelta(days=1),
        last_used_at=now,
        revoked_at=now,
    )
    fresh_db.session.add(stale)
    fresh_db.session.commit()
    stale_id = stale.id
    denied = login(client, include_refresh_token=True)
    assert denied.status_code == 409
    assert denied.json["error"] == "refresh_token_family_limit"
    assert "refresh-token" not in denied.json
    assert "no-store" in denied.headers["Cache-Control"]
    fresh_db.session.rollback()
    assert fresh_db.session.get(RefreshTokenTracker, stale_id) is None
    assert len(fresh_db.session.scalars(select(RefreshTokenTracker)).all()) == 2
    assert login(client).status_code == 200
    replacement = assert_pair(refresh(client, first["refresh-token"]), token_user.id)
    assert (
        client.post(
            "/api/revokeRefreshToken", json={"refresh-token": second["refresh-token"]}
        ).status_code
        == 200
    )
    assert_pair(login(client, include_refresh_token=True), token_user.id)
    assert_pair(refresh(client, replacement["refresh-token"]), token_user.id)


def test_family_limit_is_per_user(app, client, token_user, monkeypatch):
    monkeypatch.setitem(app.config, "FLEXMEASURES_REFRESH_TOKEN_FAMILY_LIMIT", 1)
    assert_pair(login(client, include_refresh_token=True), token_user.id)
    other = client.post(
        "/api/requestAuthToken",
        json={
            "email": "test_prosumer_user@seita.nl",
            "password": "testtest",
            "include-refresh-token": True,
        },
    )
    assert other.status_code == 200
    assert "refresh-token" in other.json
    assert login(client, include_refresh_token=True).status_code == 409


@pytest.mark.parametrize("expiry", ["absolute", "idle"])
def test_cleanup_preserves_family_at_exact_expiry_boundary(
    app, client, fresh_db, token_user, token_clock, monkeypatch, expiry
):
    token_clock(0)
    monkeypatch.setitem(app.config, "FLEXMEASURES_REFRESH_TOKEN_FAMILY_LIMIT", 1)
    if expiry == "idle":
        monkeypatch.setitem(
            app.config, "SECURITY_REFRESH_TOKEN_MAX_IDLE", timedelta(seconds=10)
        )
    pair = assert_pair(login(client, include_refresh_token=True), token_user.id)
    if expiry == "absolute":
        tracker = fresh_db.session.scalar(select(RefreshTokenTracker))
        tracker.expires_at = app.extensions["security"].datetime_factory() + timedelta(
            seconds=10
        )
        fresh_db.session.commit()
    token_clock(10)
    assert login(client, include_refresh_token=True).status_code == 409
    token_clock(11)
    assert_pair(login(client, include_refresh_token=True), token_user.id)
    assert refresh(client, pair["refresh-token"]).status_code == 401


def test_family_limit_serializes_concurrent_logins(
    app, client, fresh_db, token_user, monkeypatch
):
    monkeypatch.setitem(app.config, "FLEXMEASURES_REFRESH_TOKEN_FAMILY_LIMIT", 2)
    existing = assert_pair(login(client, include_refresh_token=True), token_user.id)
    first_inside = Event()
    release_first = Event()
    second_query = Event()
    second_inside = Event()
    thread_state = local()
    original_create = auth_tokens.new_refresh_tracker

    def paused_create(user, name):
        if getattr(thread_state, "second", False):
            second_inside.set()
        else:
            first_inside.set()
            assert release_first.wait(timeout=10)
        return original_create(user, name)

    def record(conn, cursor, statement, parameters, context, executemany):
        if (
            getattr(thread_state, "second", False)
            and "FROM fm_user" in statement
            and "WHERE fm_user.id" in statement
        ):
            second_query.set()

    monkeypatch.setattr(auth_tokens, "new_refresh_tracker", paused_create)

    def issue(second=False):
        thread_state.second = second
        with app.app_context(), app.test_client() as concurrent_client:
            response = login(concurrent_client, include_refresh_token=True)
            return response.status_code

    event.listen(fresh_db.engine, "before_cursor_execute", record)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(issue)
            try:
                assert first_inside.wait(timeout=10)
                second = executor.submit(issue, True)
                assert second_query.wait(timeout=10)
                assert not second_inside.wait(timeout=1)
            finally:
                release_first.set()
            assert sorted((first.result(timeout=20), second.result(timeout=20))) == [
                200,
                409,
            ]
    finally:
        event.remove(fresh_db.engine, "before_cursor_execute", record)
    assert len(fresh_db.session.scalars(select(RefreshTokenTracker)).all()) == 2
    assert_pair(refresh(client, existing["refresh-token"]), token_user.id)


def test_issuing_a_family_does_not_load_the_tracker_collection(
    app, client, fresh_db, token_user
):
    assert_pair(login(client, include_refresh_token=True), token_user.id)
    fresh_db.session.expire_all()
    clear_auth()
    statements = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(fresh_db.engine, "before_cursor_execute", record)
    try:
        assert_pair(login(client, include_refresh_token=True), token_user.id)
    finally:
        event.remove(fresh_db.engine, "before_cursor_execute", record)
    assert not any(
        statement.lstrip().upper().startswith("SELECT")
        and "FROM refresh_token_tracker" in statement
        and "count(" not in statement.lower()
        for statement in statements
    )


@pytest.mark.parametrize(
    "expired,revoked,expected",
    [
        (False, False, {"expired", "revoked"}),
        (True, False, {"revoked"}),
        (False, True, {"expired"}),
        (True, True, set()),
    ],
)
def test_flask_security_cleanup_options_are_preserved(
    app, fresh_db, token_user, expired, revoked, expected
):
    """The optimized datastore still honors Flask-Security's cleanup flags."""
    security = app.extensions["security"]
    now = security.datetime_factory()
    for family, expires_at, revoked_at in (
        ("expired", now - timedelta(seconds=1), None),
        ("revoked", now + timedelta(days=1), now),
    ):
        fresh_db.session.add(
            RefreshTokenTracker(
                user_id=token_user.id,
                name="default",
                refresh_family=family,
                gen=1,
                expires_at=expires_at,
                last_used_at=now,
                revoked_at=revoked_at,
            )
        )
    fresh_db.session.commit()
    security.datastore.cleanup_refresh_trackers(
        token_user, expired=expired, revoked=revoked
    )
    fresh_db.session.commit()
    assert (
        set(fresh_db.session.scalars(select(RefreshTokenTracker.refresh_family)))
        == expected
    )


def test_flask_security_cleanup_locks_user_before_pending_tracker_write(
    app, client, fresh_db, token_user
):
    assert_pair(login(client, include_refresh_token=True), token_user.id)
    token_user.refresh_trackers[0].name = "modified"
    statements = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(fresh_db.engine, "before_cursor_execute", record)
    try:
        app.extensions["security"].datastore.cleanup_refresh_trackers(token_user)
        fresh_db.session.commit()
    finally:
        event.remove(fresh_db.engine, "before_cursor_execute", record)
    first_write = next(
        i
        for i, statement in enumerate(statements)
        if statement.startswith(("UPDATE", "DELETE"))
    )
    assert any(
        "FROM fm_user" in statement and "FOR UPDATE" in statement
        for statement in statements[:first_write]
    )


@pytest.mark.parametrize("transient", [False, True])
def test_flask_security_can_issue_a_family_for_a_new_user(
    app, fresh_db, token_user, transient
):
    """Pending and transient users can still receive a Flask-Security refresh tracker."""
    security = app.extensions["security"]
    user = security.datastore.create_user(
        email="refresh-new-user@example.com",
        username="refresh-new-user",
        password=hash_password("testtest"),
        account_id=token_user.account_id,
    )
    if transient:
        fresh_db.session.expunge(user)
    tracker, token = new_refresh_tracker(user, name="default")
    fresh_db.session.commit()
    assert tracker.user_id == user.id
    assert (
        security.refresh_token_serializer.loads(token)["family"]
        == tracker.refresh_family
    )
    assert [item.id for item in user.refresh_trackers] == [tracker.id]


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
    app, client, token_user, token_clock, monkeypatch
):
    token_clock(0)
    monkeypatch.setitem(
        app.config, "SECURITY_TOKEN_EXPIRE_TIMESTAMP", lambda user: time.time() + 5
    )
    pair = assert_pair(login(client, include_refresh_token=True), token_user.id)
    assert 0 < pair["expires-in"] <= 5
    clear_auth()
    assert (
        client.get(
            url_for("AssetAPI:index"), headers={"Authorization": pair["auth_token"]}
        ).status_code
        == 200
    )
    token_clock(10)
    clear_auth()
    assert (
        client.get(
            url_for("AssetAPI:index"), headers={"Authorization": pair["auth_token"]}
        ).status_code
        == 401
    )


@pytest.mark.parametrize("per_token_expiry", [0, 30])
def test_zero_access_token_lifetime(
    app, client, token_user, token_clock, monkeypatch, per_token_expiry
):
    """Zero max age is not unlimited, even with a later per-token deadline."""
    token_clock(0)
    monkeypatch.setitem(app.config, "SECURITY_TOKEN_MAX_AGE", timedelta(0))
    monkeypatch.setitem(
        app.config,
        "SECURITY_TOKEN_EXPIRE_TIMESTAMP",
        lambda user: time.time() + per_token_expiry if per_token_expiry else 0,
    )
    response = login(client, include_refresh_token=True)
    assert response.status_code == 200
    pair = response.json
    assert pair["expires-in"] == 0
    clear_auth()
    assert (
        client.get(
            url_for("AssetAPI:index"), headers={"Authorization": pair["auth_token"]}
        ).status_code
        == 200
    )
    token_clock(2)
    clear_auth()
    assert (
        client.get(
            url_for("AssetAPI:index"), headers={"Authorization": pair["auth_token"]}
        ).status_code
        == 401
    )
    replacement = refresh(client, pair["refresh-token"])
    assert replacement.status_code == 200
    assert replacement.json["expires-in"] == 0


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
