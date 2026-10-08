from flask import url_for
import pytest
from sqlalchemy import select

from flexmeasures.api.common.rate_limiting import limiter
from flexmeasures.api.tests.utils import get_auth_token
from flexmeasures.api.v3_0.tests.utils import message_for_trigger_schedule
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.models.user import Plan, RateLimitKey, User


@pytest.fixture
def rate_limiting(app, monkeypatch):
    """Start each test with a clean count.

    Note that the limits are set very high during tests (see TestingConfig),
    so each test here lowers the limit it wants to hit.
    """
    limiter.reset()
    yield monkeypatch
    limiter.reset()


def message_for_trigger_asset_schedule(sensor: Sensor) -> dict:
    """A message the asset trigger endpoint accepts, scheduling the given power sensor.

    The asset endpoint takes a flex-model per flexible device, so we point the flex-model at the sensor.
    We also ask for a new job, so that an identical job cached by an earlier test cannot be reused,
    which would leave the queue length unchanged and tell us nothing.
    """
    message = message_for_trigger_schedule()
    message["flex-model"] = [message["flex-model"] | {"sensor": sensor.id}]
    message["force-new-job-creation"] = True
    return message


def trigger(client, asset: GenericAsset, message: dict | None = None):
    """Ask for a schedule for the asset's (first) power sensor.

    Pass ``message={}`` to have the request rejected: a message which says neither when to schedule
    nor what does not survive validation.
    """
    if message is None:
        message = message_for_trigger_asset_schedule(asset.sensors[0])
    return client.post(url_for("AssetAPI:trigger_schedule", id=asset.id), json=message)


def trigger_through_deprecated_sensor_endpoint(client, sensor: Sensor):
    """Ask for a schedule through the deprecated endpoint, which names a sensor rather than an asset."""
    return client.post(
        url_for("SensorAPI:trigger_schedule", id=sensor.id),
        json=message_for_trigger_schedule() | {"force-new-job-creation": True},
    )


def get_as(app, auth_token: str, endpoint: str = "SensorAPI:index"):
    """Call a GET endpoint as the user the token belongs to, like an API client would (by default, list sensors).

    Each request gets an app context and a client of its own.
    The tests run inside one app context, whose ``g`` would otherwise hand the user loaded by one request to the next,
    and a session cookie would do the same, so that the limiter would count each request against the previous request's user.
    """
    path = url_for(endpoint)
    with app.app_context(), app.test_client() as client:
        return client.get(path, headers={"Authorization": auth_token})


def auth_token_of(app, email: str) -> str:
    """Log in as an API client would, without spending any of the budgets we test."""
    with app.test_client() as client:
        auth_token = get_auth_token(client, email, "testtest")
    limiter.reset()  # start counting afresh, so that logging in spent nothing
    return auth_token


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_no_rate_limiting_when_disabled(
    app,
    add_market_prices,
    add_battery_assets,
    keep_scheduling_queue_empty,
    rate_limiting,
    requesting_user,
):
    """Hosts can turn rate limiting off altogether."""
    rate_limiting.setitem(
        app.config, "FLEXMEASURES_API_TRIGGER_RATE_LIMIT", "1 per day"
    )
    rate_limiting.setattr(limiter, "enabled", False)
    battery = add_battery_assets["Test battery"]
    with app.test_client() as client:
        for _ in range(3):
            assert trigger(client, battery).status_code != 429


def test_default_rate_limit(app, setup_roles_users, rate_limiting):
    """The default limit applies to any API endpoint, and says how long to wait."""
    rate_limiting.setitem(
        app.config, "FLEXMEASURES_API_DEFAULT_RATE_LIMIT", "2 per minute"
    )
    auth_token = auth_token_of(app, "test_prosumer_user@seita.nl")
    for _ in range(2):
        assert get_as(app, auth_token).status_code == 200
    response = get_as(app, auth_token)

    assert response.status_code == 429
    assert response.json["status"] == "TOO_MANY_REQUESTS"
    assert "2 per 1 minute" in response.json["message"]
    assert "Retry-After" in response.headers


@pytest.mark.parametrize(
    "other_user_email, expected_status_code_for_other_user",
    [
        # Users of the same account share one budget ...
        ("test_prosumer_user_2@seita.nl", 429),
        # ... while users of another account have a budget of their own
        ("test_dummy_user_3@seita.nl", 200),
    ],
)
def test_default_rate_limit_is_counted_per_account(
    app,
    setup_roles_users,
    rate_limiting,
    other_user_email,
    expected_status_code_for_other_user,
):
    """The default limit is one budget per account, which is what the account's plan sets."""
    rate_limiting.setitem(
        app.config, "FLEXMEASURES_API_DEFAULT_RATE_LIMIT", "2 per minute"
    )
    auth_token = auth_token_of(app, "test_prosumer_user@seita.nl")
    other_auth_token = auth_token_of(app, other_user_email)

    for _ in range(2):
        assert get_as(app, auth_token).status_code == 200
    assert get_as(app, auth_token).status_code == 429
    response = get_as(app, other_auth_token)

    assert response.status_code == expected_status_code_for_other_user


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_ui_requests_have_a_budget_per_user(
    app, setup_roles_users, rate_limiting, requesting_user
):
    """The UI calls the API with the user's session, and those requests count against the UI's budget per user."""
    rate_limiting.setitem(app.config, "FLEXMEASURES_UI_RATE_LIMIT", "2 per minute")
    with app.test_client() as client:
        for _ in range(2):
            assert client.get(url_for("SensorAPI:index")).status_code == 200
        response = client.get(url_for("SensorAPI:index"))

    assert response.status_code == 429
    assert "2 per 1 minute" in response.json["message"]


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user_2@seita.nl"], indirect=True
)
def test_an_exhausted_account_budget_does_not_lock_out_the_ui(
    app, setup_roles_users, rate_limiting, requesting_user
):
    """An integration which uses up its account's budget leaves the UI usable for the account's users."""
    rate_limiting.setitem(
        app.config, "FLEXMEASURES_API_DEFAULT_RATE_LIMIT", "2 per minute"
    )
    rate_limiting.setitem(app.config, "FLEXMEASURES_UI_RATE_LIMIT", "2 per minute")
    # An integration of the same account
    auth_token = auth_token_of(app, "test_prosumer_user@seita.nl")
    for _ in range(2):
        assert get_as(app, auth_token).status_code == 200
    assert get_as(app, auth_token).status_code == 429

    with app.test_client() as client:
        for _ in range(2):
            assert client.get(url_for("SensorAPI:index")).status_code == 200


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user_2@seita.nl"], indirect=True
)
def test_ui_requests_do_not_spend_the_account_budget(
    app, setup_roles_users, rate_limiting, requesting_user
):
    """Browsing the UI leaves the budget which the account's integrations need untouched."""
    rate_limiting.setitem(
        app.config, "FLEXMEASURES_API_DEFAULT_RATE_LIMIT", "2 per minute"
    )
    auth_token = auth_token_of(app, "test_prosumer_user@seita.nl")
    with app.test_client() as client:
        for _ in range(3):
            assert client.get(url_for("SensorAPI:index")).status_code == 200

    # An integration of the same account still has its whole budget
    for _ in range(2):
        assert get_as(app, auth_token).status_code == 200
    assert get_as(app, auth_token).status_code == 429


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
@pytest.mark.parametrize("plan_default_rate_limit", ["unlimited", "1 per minute"])
def test_plans_do_not_change_the_ui_budget(
    db, app, setup_roles_users, rate_limiting, requesting_user, plan_default_rate_limit
):
    """A plan sets the budget of the account's integrations, so it neither exempts nor limits the UI."""
    rate_limiting.setitem(app.config, "FLEXMEASURES_UI_RATE_LIMIT", "2 per minute")
    account = requesting_user.account
    account.plan = Plan(
        name=f"test-plan-ui-{plan_default_rate_limit}",
        default_rate_limit=plan_default_rate_limit,
    )
    db.session.commit()
    try:
        with app.test_client() as client:
            for _ in range(2):
                assert client.get(url_for("SensorAPI:index")).status_code == 200
            assert client.get(url_for("SensorAPI:index")).status_code == 429
    finally:
        # Take the account off the plan again, also when this test fails,
        # because later tests in this module would otherwise be limited by it.
        account.plan = None
        db.session.commit()


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_play_mode_is_exempt_from_both_rate_limits(
    app,
    add_market_prices,
    add_battery_assets,
    keep_scheduling_queue_empty,
    rate_limiting,
    requesting_user,
):
    """A play server runs simulations, which trigger in tight loops on purpose."""
    rate_limiting.setitem(app.config, "FLEXMEASURES_MODE", "play")
    rate_limiting.setitem(
        app.config, "FLEXMEASURES_API_DEFAULT_RATE_LIMIT", "1 per minute"
    )
    rate_limiting.setitem(app.config, "FLEXMEASURES_UI_RATE_LIMIT", "1 per minute")
    rate_limiting.setitem(
        app.config, "FLEXMEASURES_API_TRIGGER_RATE_LIMIT", "1 per 5 minutes"
    )
    battery = add_battery_assets["Test battery"]
    with app.test_client() as client:
        for _ in range(3):
            assert client.get(url_for("SensorAPI:index")).status_code == 200
            assert trigger(client, battery).status_code != 429


def test_development_mode_still_rate_limits(app, setup_roles_users, rate_limiting):
    """Only the play mode is exempt: a dev server limits like production does,
    so that the limits do not first surface once they are live."""
    rate_limiting.setitem(app.config, "FLEXMEASURES_MODE", "development")
    rate_limiting.setitem(
        app.config, "FLEXMEASURES_API_DEFAULT_RATE_LIMIT", "1 per minute"
    )
    auth_token = auth_token_of(app, "test_prosumer_user@seita.nl")
    assert get_as(app, auth_token).status_code == 200
    assert get_as(app, auth_token).status_code == 429


def test_health_endpoint_is_exempt_from_default_rate_limit(
    app, setup_roles_users, rate_limiting
):
    """Monitoring should not be able to rate-limit itself out of checking on us."""
    rate_limiting.setitem(
        app.config, "FLEXMEASURES_API_DEFAULT_RATE_LIMIT", "1 per minute"
    )
    auth_token = auth_token_of(app, "test_prosumer_user@seita.nl")
    for _ in range(3):
        assert get_as(app, auth_token, "HealthAPI:is_ready").status_code == 200


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_trigger_rate_limit(
    app,
    add_market_prices,
    add_battery_assets,
    keep_scheduling_queue_empty,
    rate_limiting,
    requesting_user,
):
    """A schedule can be triggered successfully, but not again right away."""
    rate_limiting.setitem(
        app.config, "FLEXMEASURES_API_TRIGGER_RATE_LIMIT", "1 per 5 minutes"
    )
    battery = add_battery_assets["Test battery"]
    scheduling_queue = app.queues["scheduling"]

    with app.test_client() as client:
        assert trigger(client, battery).status_code == 202

        # The accepted trigger queued a scheduling job
        assert len(scheduling_queue) == 1

        response = trigger(client, battery)

    assert response.status_code == 429
    assert response.json["status"] == "TOO_MANY_REQUESTS"

    # The rate-limited trigger did no work
    assert len(scheduling_queue) == 1


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_rejected_triggers_do_not_spend_the_trigger_budget(
    app,
    add_market_prices,
    add_battery_assets,
    keep_scheduling_queue_empty,
    rate_limiting,
    requesting_user,
):
    """The trigger budget is only spent on triggers which set computation in motion.

    A request we refuse costs us no schedule, so the client keeps their budget. That goes for any
    request we refuse, whatever the reason (this test uses an invalid payload, but a request without
    permission is refused in the same way), because the deduction keys off the response status.

    Note that refused requests are still counted by the default limit, which is what bounds a client
    who keeps sending us requests we refuse.
    """
    rate_limiting.setitem(
        app.config, "FLEXMEASURES_API_TRIGGER_RATE_LIMIT", "1 per 5 minutes"
    )
    battery = add_battery_assets["Test battery"]

    with app.test_client() as client:
        # We reject these, because the message says neither when to schedule nor what
        for _ in range(3):
            assert trigger(client, battery, message={}).status_code == 422

        # The budget is still there for a trigger we do accept ...
        assert trigger(client, battery).status_code == 202
        # ... and now it is spent
        assert trigger(client, battery).status_code == 429


@pytest.mark.parametrize(
    "rate_limit_key, expected_status_code_for_other_asset",
    [
        # Each asset gets its own budget ...
        (RateLimitKey.ACCOUNT_PLUS_ASSET.value, 202),
        # ... unless the whole account or user shares one budget
        (RateLimitKey.ACCOUNT.value, 429),
        (RateLimitKey.USER.value, 429),
    ],
)
@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_trigger_rate_limit_key(
    app,
    add_market_prices,
    add_battery_assets,
    keep_scheduling_queue_empty,
    rate_limiting,
    requesting_user,
    rate_limit_key,
    expected_status_code_for_other_asset,
):
    """The host decides whether the trigger limit is counted per asset, per account or per user."""
    rate_limiting.setitem(app.config, "FLEXMEASURES_API_RATE_LIMIT_KEY", rate_limit_key)
    rate_limiting.setitem(
        app.config, "FLEXMEASURES_API_TRIGGER_RATE_LIMIT", "1 per 5 minutes"
    )
    battery = add_battery_assets["Test battery"]
    other_battery = add_battery_assets["Test small battery"]

    with app.test_client() as client:
        assert trigger(client, battery).status_code == 202  # spends the budget
        assert trigger(client, battery).status_code == 429
        response = trigger(client, other_battery)

    assert response.status_code == expected_status_code_for_other_asset


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_deprecated_sensor_endpoint_shares_the_asset_budget(
    app,
    add_market_prices,
    add_battery_assets,
    keep_scheduling_queue_empty,
    rate_limiting,
    requesting_user,
):
    """Triggering an asset's sensor through the deprecated endpoint spends that asset's budget.

    Otherwise, a client could double their budget by alternating between the two endpoints.
    """
    rate_limiting.setitem(
        app.config,
        "FLEXMEASURES_API_RATE_LIMIT_KEY",
        RateLimitKey.ACCOUNT_PLUS_ASSET.value,
    )
    rate_limiting.setitem(
        app.config, "FLEXMEASURES_API_TRIGGER_RATE_LIMIT", "1 per 5 minutes"
    )
    battery = add_battery_assets["Test battery"]

    with app.test_client() as client:
        assert trigger(client, battery).status_code == 202  # spends the asset's budget
        response = trigger_through_deprecated_sensor_endpoint(
            client, battery.sensors[0]
        )

    assert response.status_code == 429


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_account_can_override_trigger_rate_limit(
    db,
    app,
    add_market_prices,
    add_battery_assets,
    keep_scheduling_queue_empty,
    rate_limiting,
    requesting_user,
):
    """An account's own limit takes precedence over the configured default."""
    rate_limiting.setitem(
        app.config, "FLEXMEASURES_API_TRIGGER_RATE_LIMIT", "1 per 5 minutes"
    )
    requesting_user.account.plan = Plan(
        name="test-plan-override", trigger_rate_limit="2 per 5 minutes"
    )
    db.session.commit()
    battery = add_battery_assets["Test battery"]

    with app.test_client() as client:
        for _ in range(2):
            assert trigger(client, battery).status_code == 202
        assert trigger(client, battery).status_code == 429


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_account_can_be_exempt_from_trigger_rate_limit(
    db,
    app,
    add_market_prices,
    add_battery_assets,
    keep_scheduling_queue_empty,
    rate_limiting,
    requesting_user,
):
    """An account can be exempted from a limit altogether."""
    rate_limiting.setitem(
        app.config, "FLEXMEASURES_API_TRIGGER_RATE_LIMIT", "1 per 5 minutes"
    )
    requesting_user.account.plan = Plan(
        name="test-plan-unlimited", trigger_rate_limit="unlimited"
    )
    db.session.commit()
    battery = add_battery_assets["Test battery"]

    with app.test_client() as client:
        for _ in range(3):
            assert trigger(client, battery).status_code == 202


def test_account_can_be_exempt_from_default_rate_limit(
    db, app, setup_roles_users, rate_limiting
):
    """An account can be exempted from the default limit, too.

    This also covers that the "unlimited" sentinel never reaches the limit parser:
    the exemption is granted by exempt_when, while the limit callable falls back
    to the server config.
    """
    rate_limiting.setitem(
        app.config, "FLEXMEASURES_API_DEFAULT_RATE_LIMIT", "1 per minute"
    )
    user = db.session.execute(
        select(User).filter_by(email="test_prosumer_user@seita.nl")
    ).scalar_one()
    user.account.plan = Plan(
        name="test-plan-default-unlimited", default_rate_limit="unlimited"
    )
    db.session.commit()

    auth_token = auth_token_of(app, user.email)
    for _ in range(3):
        assert get_as(app, auth_token).status_code == 200


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_plan_rate_limit_key_overrides_config(
    db,
    app,
    add_market_prices,
    add_battery_assets,
    keep_scheduling_queue_empty,
    rate_limiting,
    requesting_user,
):
    """A plan's rate_limit_key takes precedence over the server-wide config setting."""
    rate_limiting.setitem(
        app.config,
        "FLEXMEASURES_API_RATE_LIMIT_KEY",
        RateLimitKey.ACCOUNT_PLUS_ASSET.value,
    )
    rate_limiting.setitem(
        app.config, "FLEXMEASURES_API_TRIGGER_RATE_LIMIT", "1 per 5 minutes"
    )
    requesting_user.account.plan = Plan(
        name="test-plan-key", rate_limit_key=RateLimitKey.ACCOUNT
    )
    db.session.commit()
    battery = add_battery_assets["Test battery"]
    other_battery = add_battery_assets["Test small battery"]

    with app.test_client() as client:
        assert trigger(client, battery).status_code == 202  # spends the budget
        # The account-level key means the other asset shares the same budget
        assert trigger(client, other_battery).status_code == 429


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_invalid_rate_limit_key_falls_back_instead_of_erroring(
    app,
    add_market_prices,
    add_battery_assets,
    keep_scheduling_queue_empty,
    rate_limiting,
    requesting_user,
):
    """A bad FLEXMEASURES_API_RATE_LIMIT_KEY must not turn every request into a 500.

    We fall back to counting against the account, which is what we count against by default.
    """
    rate_limiting.setitem(
        app.config, "FLEXMEASURES_API_RATE_LIMIT_KEY", "not-a-real-key"
    )
    rate_limiting.setitem(
        app.config, "FLEXMEASURES_API_TRIGGER_RATE_LIMIT", "1 per 5 minutes"
    )
    battery = add_battery_assets["Test battery"]
    other_battery = add_battery_assets["Test small battery"]

    with app.test_client() as client:
        assert trigger(client, battery).status_code == 202
        assert trigger(client, other_battery).status_code == 429


def test_openapi_specs_document_the_429_response():
    """Every rate-limited endpoint documents that it can answer with a 429.

    The limiter guards these endpoints from outside the views, so no view docstring
    declares this response; the specs generator adds it (see document_rate_limits).
    """
    from flexmeasures.api.v3_0 import document_rate_limits

    spec_dict = {
        "paths": {
            "/api/v3_0/assets": {
                "get": {"responses": {"200": {"description": "PROCESSED"}}}
            },
            "/api/v3_0/assets/{id}/schedules/trigger": {"post": {}},
            "/api/v3_0/health/ready": {"get": {}},
            "/": {"get": {}},
        }
    }
    document_rate_limits(
        spec_dict, {("/api/v3_0/assets/{id}/schedules/trigger", "post")}
    )

    paths = spec_dict["paths"]
    assert "429" in paths["/api/v3_0/assets"]["get"]["responses"]
    assert "200" in paths["/api/v3_0/assets"]["get"]["responses"]  # still there
    trigger_429 = paths["/api/v3_0/assets/{id}/schedules/trigger"]["post"]["responses"][
        "429"
    ]
    assert "stricter limit" in trigger_429["description"]
    # The health endpoints are exempt, and only the API is rate-limited
    assert "responses" not in paths["/api/v3_0/health/ready"]["get"]
    assert "responses" not in paths["/"]["get"]


def test_trigger_limited_views_are_registered():
    """The specs generator recognizes trigger endpoints by the view's qualified name,
    so make sure decorating a view still registers it."""
    from flexmeasures.api.common.rate_limiting import TRIGGER_LIMITED_VIEWS

    assert {
        "AssetAPI.trigger_report",
        "AssetAPI.trigger_schedule",
        "SensorAPI.trigger_schedule",
        "SensorAPI.trigger_forecast",
    } <= TRIGGER_LIMITED_VIEWS
