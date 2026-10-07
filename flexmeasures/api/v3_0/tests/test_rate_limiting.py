from flask import url_for
import pytest
from sqlalchemy import select

import logging

from flexmeasures.api.common.rate_limiting import (
    limiter,
    warn_about_deprecated_settings,
)
from flexmeasures.api.v3_0.tests.utils import message_for_trigger_schedule
from flexmeasures.cli.tests.utils import check_command_ran_without_error
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.models.user import Account, Plan


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
def without_plan(db, requesting_user):
    """Take the requesting user's account off any plan, which earlier tests in this module may have put it on."""
    requesting_user.account.plan = None
    db.session.commit()
    return requesting_user


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


def reset(app, account: Account, *options: str):
    """Reset the account's rate limits, as a host would from the command line."""
    from flexmeasures.cli.data_edit import reset_rate_limit

    result = app.test_cli_runner().invoke(
        reset_rate_limit, ["--account", str(account.id), *options]
    )
    check_command_ran_without_error(result)
    return result


def trigger_through_deprecated_sensor_endpoint(client, sensor: Sensor):
    """Ask for a schedule through the deprecated endpoint, which names a sensor rather than an asset."""
    return client.post(
        url_for("SensorAPI:trigger_schedule", id=sensor.id),
        json=message_for_trigger_schedule() | {"force-new-job-creation": True},
    )


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


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_account_can_be_exempt_from_default_rate_limit(
    db, app, rate_limiting, requesting_user
):
    """An account can be exempted from the default limit, too.

    This also covers that the "unlimited" sentinel never reaches the limit parser:
    the exemption is granted by exempt_when, while the limit callable falls back
    to the server config.
    """
    rate_limiting.setitem(
        app.config, "FLEXMEASURES_API_DEFAULT_RATE_LIMIT", "1 per minute"
    )
    requesting_user.account.plan = Plan(
        name="test-plan-default-unlimited", default_rate_limit="unlimited"
    )
    db.session.commit()

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


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_reset_rate_limit_lets_an_account_trigger_again(
    app,
    add_market_prices,
    add_battery_assets,
    keep_scheduling_queue_empty,
    rate_limiting,
    requesting_user,
    without_plan,
):
    """After a reset, an account that was refused can trigger again straight away, rather than wait out the window."""
    rate_limiting.setitem(
        app.config, "FLEXMEASURES_API_TRIGGER_RATE_LIMIT", "1 per 5 minutes"
    )
    battery = add_battery_assets["Test battery"]

    with app.test_client() as client:
        assert trigger(client, battery).status_code == 202  # spends the budget
        assert trigger(client, battery).status_code == 429

        result = reset(app, requesting_user.account)
        assert "Reset the trigger and default rate limits" in result.output

        assert trigger(client, battery).status_code == 202
        assert trigger(client, battery).status_code == 429  # one full budget, not more


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_reset_rate_limit_leaves_other_accounts_alone(
    db,
    app,
    add_market_prices,
    add_battery_assets,
    keep_scheduling_queue_empty,
    rate_limiting,
    requesting_user,
    without_plan,
):
    """Resetting one account's rate limits does not hand another account a fresh budget."""
    rate_limiting.setitem(
        app.config, "FLEXMEASURES_API_TRIGGER_RATE_LIMIT", "1 per 5 minutes"
    )
    battery = add_battery_assets["Test battery"]
    other_account = (
        db.session.execute(
            select(Account).filter(Account.id != requesting_user.account_id)
        )
        .scalars()
        .first()
    )

    with app.test_client() as client:
        assert trigger(client, battery).status_code == 202  # spends the budget
        reset(app, other_account)
        assert trigger(client, battery).status_code == 429


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_reset_rate_limit_can_reset_one_limit(
    app, rate_limiting, requesting_user, without_plan
):
    """The --limit option resets only the limit it names."""
    rate_limiting.setitem(
        app.config, "FLEXMEASURES_API_DEFAULT_RATE_LIMIT", "1 per minute"
    )
    with app.test_client() as client:
        assert client.get(url_for("SensorAPI:index")).status_code == 200
        assert client.get(url_for("SensorAPI:index")).status_code == 429

        reset(app, requesting_user.account, "--limit", "trigger")
        assert client.get(url_for("SensorAPI:index")).status_code == 429

        reset(app, requesting_user.account, "--limit", "default")
        assert client.get(url_for("SensorAPI:index")).status_code == 200


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_reset_rate_limit_resets_the_plans_limit(
    db,
    app,
    add_market_prices,
    add_battery_assets,
    keep_scheduling_queue_empty,
    rate_limiting,
    requesting_user,
    without_plan,
):
    """The reset clears the counter of the limit in effect for the account, which its plan sets.

    The limit's amount is part of the counter's key, so clearing the server-wide limit's counter would leave this account refused.
    """
    rate_limiting.setitem(
        app.config, "FLEXMEASURES_API_TRIGGER_RATE_LIMIT", "1 per 5 minutes"
    )
    requesting_user.account.plan = Plan(
        name="test-plan-reset", trigger_rate_limit="2 per 5 minutes"
    )
    db.session.commit()
    battery = add_battery_assets["Test battery"]

    with app.test_client() as client:
        for _ in range(2):
            assert trigger(client, battery).status_code == 202
        assert trigger(client, battery).status_code == 429

        reset(app, requesting_user.account, "--limit", "trigger")
        assert trigger(client, battery).status_code == 202


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_reset_rate_limit_skips_a_limit_the_account_is_exempt_from(
    db, app, rate_limiting, requesting_user, without_plan
):
    """An account exempt from a limit has nothing to reset there, and hears so."""
    requesting_user.account.plan = Plan(
        name="test-plan-reset-unlimited", trigger_rate_limit="unlimited"
    )
    db.session.commit()

    result = reset(app, requesting_user.account)

    assert "is exempt from the trigger rate limit" in result.output
    assert "Reset the default rate limit of" in result.output


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
