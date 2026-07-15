from flask import url_for
import pytest

from flexmeasures.api.common.rate_limiting import limiter
from flexmeasures.api.v3_0.tests.utils import message_for_trigger_schedule
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.models.user import Plan, RateLimitKey


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
        assert trigger(client, battery).status_code == 200

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
        assert trigger(client, battery).status_code == 200
        # ... and now it is spent
        assert trigger(client, battery).status_code == 429


@pytest.mark.parametrize(
    "rate_limit_key, expected_status_code_for_other_asset",
    [
        # Each asset gets its own budget ...
        (RateLimitKey.ACCOUNT_PLUS_ASSET.value, 200),
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
        assert trigger(client, battery).status_code == 200  # spends the budget
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
        assert trigger(client, battery).status_code == 200  # spends the asset's budget
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
            assert trigger(client, battery).status_code == 200
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
            assert trigger(client, battery).status_code == 200


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
        assert trigger(client, battery).status_code == 200  # spends the budget
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
        assert trigger(client, battery).status_code == 200
        assert trigger(client, other_battery).status_code == 429
