"""Sentry gets no personal data unless the host opts in."""

import pytest
import sentry_sdk
from flask_login import login_user, logout_user

from flexmeasures.data.services.users import find_user_by_email
from flexmeasures.utils.app_utils import init_sentry


@pytest.fixture
def sentry_options(app, monkeypatch):
    options = {}
    monkeypatch.setitem(app.config, "SENTRY_DSN", "https://public@example.com/1")
    monkeypatch.setitem(
        app.config, "FLEXMEASURES_DO_NOT_SEND_NOTFOUND_TO_SENTRY", False
    )
    monkeypatch.setattr(
        "flexmeasures.utils.app_utils._make_sentry_redis_connection",
        lambda _app: app.redis_connection,
    )
    monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: options.update(kwargs))
    return options


def test_sentry_gets_no_personal_data_by_default(
    app, db, setup_roles_users, monkeypatch, sentry_options
):
    monkeypatch.setitem(app.config, "FLEXMEASURES_SENTRY_CONFIG", {})
    init_sentry(app)
    assert sentry_options["send_default_pii"] is False

    user = find_user_by_email("test_prosumer_user@seita.nl")
    with app.test_request_context("/"):
        login_user(user)
        event = sentry_options["before_send"]({"message": "error"}, {})
        logout_user()
    assert event["user"] == {"id": str(user.id)}


def test_host_can_opt_in_to_personal_data(app, monkeypatch, sentry_options):
    monkeypatch.setitem(
        app.config,
        "FLEXMEASURES_SENTRY_CONFIG",
        {"send_default_pii": True, "traces_sample_rate": 0.1},
    )
    init_sentry(app)
    assert sentry_options["send_default_pii"] is True
    assert sentry_options["traces_sample_rate"] == 0.1


def test_sentry_gets_account_tag_and_links_to_user_and_account_pages(
    app, db, setup_roles_users, monkeypatch, sentry_options
):
    """Events link to the platform's user and account pages (which need a login), and carry no names or emails."""
    monkeypatch.setitem(app.config, "FLEXMEASURES_SENTRY_CONFIG", {})
    init_sentry(app)

    user = find_user_by_email("test_prosumer_user@seita.nl")
    with app.test_request_context("/", base_url="https://fm.example.com"):
        login_user(user)
        event = sentry_options["before_send"]({"message": "error"}, {})
        logout_user()
    assert event["user"] == {"id": str(user.id)}
    assert event["tags"]["account_id"] == str(user.account_id)
    assert event["contexts"]["flexmeasures"] == {
        "user_page": f"https://fm.example.com/users/{user.id}",
        "account_page": f"https://fm.example.com/accounts/{user.account_id}",
    }
    assert user.email not in str(event)
    assert user.username not in str(event)


def test_sentry_event_untouched_without_logged_in_user(
    app, db, setup_roles_users, monkeypatch, sentry_options
):
    monkeypatch.setitem(app.config, "FLEXMEASURES_SENTRY_CONFIG", {})
    init_sentry(app)

    # No request at all (e.g. in a worker)
    event = sentry_options["before_send"]({"message": "error"}, {})
    assert event == {"message": "error"}

    # A request, but nobody logged in
    with app.test_request_context("/"):
        event = sentry_options["before_send"]({"message": "error"}, {})
    assert event == {"message": "error"}
