import logging

from unittest.mock import Mock
from flask import Flask, request, url_for
import pytest

from flexmeasures.api.tests.utils import get_auth_token
from flexmeasures.api.common import rate_limiting as rate_limiting_module
from flexmeasures.api.common.rate_limiting import (
    _asset_id_of_trigger,
    limiter,
    warn_about_deprecated_settings,
)
from flexmeasures.api.v3_0.tests.utils import message_for_trigger_schedule
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.models.user import Plan


@pytest.fixture
def rate_limiting(app, monkeypatch):
    """Start each test with a clean count.

    Note that the limits are set very high during tests (see TestingConfig),
    so each test here lowers the limit it wants to hit.
    """
    limiter.reset()
    yield monkeypatch
    limiter.reset()


@pytest.fixture
def assign_temporary_account_plan(db, requesting_user):
    """Assign a new plan to the shared account, then remove that plan after the test."""
    original_plan = requesting_user.account.plan
    created_plans = []

    def assign(**plan_fields):
        plan = Plan(**plan_fields)
        requesting_user.account.plan = plan
        db.session.commit()
        created_plans.append(plan)

    yield assign

    requesting_user.account.plan = original_plan
    db.session.flush()
    for plan in created_plans:
        db.session.delete(plan)
    db.session.commit()


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


def test_asset_id_of_trigger(monkeypatch):
    """
    Test the util function we use to log which asset lead to 429 status.
    Asset and sensor triggers resolve to the same asset ID.
    """
    app = Flask(__name__)
    mocked_db = Mock()
    mocked_db.session.get.return_value.generic_asset_id = 42
    monkeypatch.setattr(rate_limiting_module, "db", mocked_db)

    with app.test_request_context("/api/v3_0/assets/42/trigger_schedule"):
        request.view_args = {"id": "42"}
        assert _asset_id_of_trigger() == 42
        mocked_db.session.get.assert_not_called()

    with app.test_request_context("/api/v3_0/sensors/7/trigger_schedule"):
        request.view_args = {"id": "7"}
        assert _asset_id_of_trigger() == 42
        mocked_db.session.get.assert_called_once_with(Sensor, 7)


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


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_default_rate_limit(app, rate_limiting, requesting_user):
    """The default limit applies to any API endpoint, and says how long to wait."""
    rate_limiting.setitem(
        app.config, "FLEXMEASURES_API_DEFAULT_RATE_LIMIT", "2 per minute"
    )
    with app.test_client() as client:
        for _ in range(2):
            assert client.get(url_for("SensorAPI:index")).status_code == 200
        response = client.get(url_for("SensorAPI:index"))

    assert response.status_code == 429
    assert response.json["status"] == "TOO_MANY_REQUESTS"
    assert "2 per 1 minute" in response.json["message"]
    assert "Retry-After" in response.headers


def list_sensors_as(app, auth_token: str):
    """List sensors as the user the token belongs to, like a separate API client would.

    Each request gets an app context and a client of its own.
    The tests run inside one app context, whose ``g`` would otherwise hand the user loaded by one request to the next,
    and a session cookie would do the same, so that the limiter would count each request against the previous request's user.
    """
    path = url_for("SensorAPI:index")
    with app.app_context(), app.test_client() as client:
        return client.get(path, headers={"Authorization": auth_token})


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
    with app.test_client() as client:
        auth_token = get_auth_token(client, "test_prosumer_user@seita.nl", "testtest")
        other_auth_token = get_auth_token(client, other_user_email, "testtest")
    limiter.reset()  # start counting afresh, so that logging in spent nothing

    for _ in range(2):
        assert list_sensors_as(app, auth_token).status_code == 200
    assert list_sensors_as(app, auth_token).status_code == 429
    response = list_sensors_as(app, other_auth_token)

    assert response.status_code == expected_status_code_for_other_user


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
    rate_limiting.setitem(
        app.config, "FLEXMEASURES_API_TRIGGER_RATE_LIMIT", "1 per 5 minutes"
    )
    battery = add_battery_assets["Test battery"]
    with app.test_client() as client:
        for _ in range(3):
            assert client.get(url_for("SensorAPI:index")).status_code == 200
            assert trigger(client, battery).status_code != 429


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_development_mode_still_rate_limits(app, rate_limiting, requesting_user):
    """Only the play mode is exempt: a dev server limits like production does,
    so that the limits do not first surface once they are live."""
    rate_limiting.setitem(app.config, "FLEXMEASURES_MODE", "development")
    rate_limiting.setitem(
        app.config, "FLEXMEASURES_API_DEFAULT_RATE_LIMIT", "1 per minute"
    )
    with app.test_client() as client:
        assert client.get(url_for("SensorAPI:index")).status_code == 200
        assert client.get(url_for("SensorAPI:index")).status_code == 429


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_health_endpoint_is_exempt_from_default_rate_limit(
    app, rate_limiting, requesting_user
):
    """Monitoring should not be able to rate-limit itself out of checking on us."""
    rate_limiting.setitem(
        app.config, "FLEXMEASURES_API_DEFAULT_RATE_LIMIT", "1 per minute"
    )
    with app.test_client() as client:
        for _ in range(3):
            assert client.get(url_for("HealthAPI:is_ready")).status_code == 200


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
    # The deprecated setting no longer chooses what triggers are counted against
    "deprecated_rate_limit_key",
    [None, "account", "account+asset", "user"],
)
@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_assets_of_an_account_share_one_trigger_budget(
    app,
    add_market_prices,
    add_battery_assets,
    keep_scheduling_queue_empty,
    rate_limiting,
    requesting_user,
    deprecated_rate_limit_key,
):
    """Triggers are counted per account, so spending the budget on one asset leaves none for another."""
    if deprecated_rate_limit_key is not None:
        rate_limiting.setitem(
            app.config, "FLEXMEASURES_API_RATE_LIMIT_KEY", deprecated_rate_limit_key
        )
    rate_limiting.setitem(
        app.config, "FLEXMEASURES_API_TRIGGER_RATE_LIMIT", "1 per 5 minutes"
    )
    battery = add_battery_assets["Test battery"]
    other_battery = add_battery_assets["Test small battery"]

    with app.test_client() as client:
        assert trigger(client, battery).status_code == 202  # spends the budget
        assert trigger(client, battery).status_code == 429
        assert trigger(client, other_battery).status_code == 429


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_deprecated_sensor_endpoint_shares_the_trigger_budget(
    app,
    add_market_prices,
    add_battery_assets,
    keep_scheduling_queue_empty,
    rate_limiting,
    requesting_user,
):
    """Triggering an asset's sensor through the deprecated endpoint spends the same budget as the asset endpoint.

    Otherwise, a client could double their budget by alternating between the two endpoints.
    """
    rate_limiting.setitem(
        app.config, "FLEXMEASURES_API_TRIGGER_RATE_LIMIT", "1 per 5 minutes"
    )
    battery = add_battery_assets["Test battery"]

    with app.test_client() as client:
        assert trigger(client, battery).status_code == 202  # spends the budget
        response = trigger_through_deprecated_sensor_endpoint(
            client, battery.sensors[0]
        )

    assert response.status_code == 429


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_account_can_override_trigger_rate_limit(
    app,
    add_market_prices,
    add_battery_assets,
    keep_scheduling_queue_empty,
    rate_limiting,
    requesting_user,
    assign_temporary_account_plan,
):
    """An account's own limit takes precedence over the configured default."""
    rate_limiting.setitem(
        app.config, "FLEXMEASURES_API_TRIGGER_RATE_LIMIT", "1 per 5 minutes"
    )
    assign_temporary_account_plan(
        name="test-plan-override", trigger_rate_limit="2 per 5 minutes"
    )
    battery = add_battery_assets["Test battery"]

    with app.test_client() as client:
        for _ in range(2):
            assert trigger(client, battery).status_code == 202
        assert trigger(client, battery).status_code == 429


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_account_can_be_exempt_from_trigger_rate_limit(
    app,
    add_market_prices,
    add_battery_assets,
    keep_scheduling_queue_empty,
    rate_limiting,
    requesting_user,
    assign_temporary_account_plan,
):
    """An account can be exempted from a limit altogether."""
    rate_limiting.setitem(
        app.config, "FLEXMEASURES_API_TRIGGER_RATE_LIMIT", "1 per 5 minutes"
    )
    assign_temporary_account_plan(
        name="test-plan-unlimited", trigger_rate_limit="unlimited"
    )
    battery = add_battery_assets["Test battery"]

    with app.test_client() as client:
        for _ in range(3):
            assert trigger(client, battery).status_code == 202


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_account_can_be_exempt_from_default_rate_limit(
    app, rate_limiting, requesting_user, assign_temporary_account_plan
):
    """An account can be exempted from the default limit, too.

    This also covers that the "unlimited" sentinel never reaches the limit parser:
    the exemption is granted by exempt_when, while the limit callable falls back
    to the server config.
    """
    rate_limiting.setitem(
        app.config, "FLEXMEASURES_API_DEFAULT_RATE_LIMIT", "1 per minute"
    )
    assign_temporary_account_plan(
        name="test-plan-default-unlimited", default_rate_limit="unlimited"
    )

    with app.test_client() as client:
        for _ in range(3):
            assert client.get(url_for("SensorAPI:index")).status_code == 200


@pytest.mark.parametrize(
    "deprecated_rate_limit_key, expect_warning",
    [
        (None, False),
        ("account", False),
        ("account+asset", True),
        ("user", True),
        ("not-a-real-key", True),
    ],
)
def test_deprecated_rate_limit_key_is_warned_about(
    app, rate_limiting, caplog, deprecated_rate_limit_key, expect_warning
):
    """Hosts who still choose what triggers are counted against hear that this setting is ignored now."""
    if deprecated_rate_limit_key is None:
        rate_limiting.delitem(app.config, "FLEXMEASURES_API_RATE_LIMIT_KEY")
    else:
        rate_limiting.setitem(
            app.config, "FLEXMEASURES_API_RATE_LIMIT_KEY", deprecated_rate_limit_key
        )

    with caplog.at_level(logging.WARNING):
        warn_about_deprecated_settings(app)

    warned = "FLEXMEASURES_API_RATE_LIMIT_KEY is deprecated" in caplog.text
    assert warned is expect_warning


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


def refusal_logs(caplog) -> list[str]:
    """The warnings we logged for requests refused by a rate limit."""
    return [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.WARNING
        and record.getMessage().startswith("Refused a request for hitting")
    ]


@pytest.mark.parametrize("through_deprecated_sensor_endpoint", [False, True])
@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_hitting_the_trigger_rate_limit_is_logged(
    app,
    add_market_prices,
    add_battery_assets,
    keep_scheduling_queue_empty,
    rate_limiting,
    requesting_user,
    caplog,
    through_deprecated_sensor_endpoint,
):
    """A host can tell from the logs who spent an account's trigger budget, on which asset and endpoint.

    The deprecated sensor endpoint names a sensor rather than an asset, and we still log the asset.
    """
    rate_limiting.setitem(
        app.config, "FLEXMEASURES_API_TRIGGER_RATE_LIMIT", "1 per 5 minutes"
    )
    battery = add_battery_assets["Test battery"]

    with app.test_client() as client:
        assert trigger(client, battery).status_code == 202  # spends the budget
        if through_deprecated_sensor_endpoint:
            response = trigger_through_deprecated_sensor_endpoint(
                client, battery.sensors[0]
            )
            endpoint = "SensorAPI:trigger_schedule"
            path = url_for(endpoint, id=battery.sensors[0].id)
        else:
            response = trigger(client, battery)
            endpoint = "AssetAPI:trigger_schedule"
            path = url_for(endpoint, id=battery.id)

    assert response.status_code == 429
    assert refusal_logs(caplog) == [
        f"Refused a request for hitting the trigger rate limit (1 per 5 minute): "
        f"account {requesting_user.account_id}, user {requesting_user.id}, asset {battery.id}, "
        f"POST {path} ({endpoint})."
    ]


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_hitting_the_default_rate_limit_is_logged(
    app, rate_limiting, requesting_user, caplog
):
    """The default limit spans the whole API, so we log the endpoint, but no asset."""
    rate_limiting.setitem(
        app.config, "FLEXMEASURES_API_DEFAULT_RATE_LIMIT", "1 per minute"
    )
    with app.test_client() as client:
        assert client.get(url_for("SensorAPI:index")).status_code == 200
        assert client.get(url_for("SensorAPI:index")).status_code == 429

    assert refusal_logs(caplog) == [
        f"Refused a request for hitting the default rate limit (1 per 1 minute): "
        f"account {requesting_user.account_id}, user {requesting_user.id}, "
        f"GET {url_for('SensorAPI:index')} (SensorAPI:index)."
    ]


def test_hitting_the_default_rate_limit_unauthenticated_is_logged(
    app, rate_limiting, caplog
):
    """Without a user to attribute a request to, we log the IP address it was counted against."""
    rate_limiting.setitem(
        app.config, "FLEXMEASURES_API_DEFAULT_RATE_LIMIT", "1 per minute"
    )
    with app.test_client() as client:
        client.get(url_for("SensorAPI:index"))
        assert client.get(url_for("SensorAPI:index")).status_code == 429

    assert refusal_logs(caplog) == [
        "Refused a request for hitting the default rate limit (1 per 1 minute): "
        f"unauthenticated caller 127.0.0.1, GET {url_for('SensorAPI:index')} (SensorAPI:index)."
    ]


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_counted_triggers_are_logged_at_debug_level(
    app,
    add_market_prices,
    add_battery_assets,
    keep_scheduling_queue_empty,
    rate_limiting,
    requesting_user,
    caplog,
):
    """Each trigger which spends budget is logged at debug level, and a trigger we refuse is not."""
    battery = add_battery_assets["Test battery"]

    with caplog.at_level(logging.DEBUG, logger=app.logger.name):
        with app.test_client() as client:
            assert trigger(client, battery, message={}).status_code == 422
            assert trigger(client, battery).status_code == 202

    counted = [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.DEBUG
        and record.getMessage().startswith("Counted a trigger")
    ]
    assert counted == [
        f"Counted a trigger against the trigger rate limit: "
        f"account {requesting_user.account_id}, user {requesting_user.id}, asset {battery.id}, "
        f"POST {url_for('AssetAPI:trigger_schedule', id=battery.id)} (AssetAPI:trigger_schedule)."
    ]
