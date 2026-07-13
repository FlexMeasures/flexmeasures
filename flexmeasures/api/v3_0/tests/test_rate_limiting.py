from flask import url_for
import pytest

from flexmeasures.api.common.rate_limiting import limiter
from flexmeasures.api.v3_0.tests.utils import message_for_trigger_schedule
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


def trigger(client, sensor_id: int, message: dict | None = None):
    """Post to the schedule trigger endpoint.

    Note that the limiter counts a request before its payload is validated,
    so tests which only care about counting may pass an empty message.
    """
    return client.post(
        url_for("SensorAPI:trigger_schedule", id=sensor_id),
        json=message if message is not None else {},
    )


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_no_rate_limiting_when_disabled(
    app, add_battery_assets, rate_limiting, requesting_user
):
    """Hosts can turn rate limiting off altogether."""
    rate_limiting.setitem(
        app.config, "FLEXMEASURES_API_TRIGGER_RATE_LIMIT", "1 per day"
    )
    rate_limiting.setattr(limiter, "enabled", False)
    sensor = add_battery_assets["Test battery"].sensors[0]
    with app.test_client() as client:
        for _ in range(3):
            assert trigger(client, sensor.id).status_code != 429


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
    add_charging_station_assets,
    keep_scheduling_queue_empty,
    rate_limiting,
    requesting_user,
):
    """A schedule can be triggered successfully, but not again right away."""
    rate_limiting.setitem(
        app.config, "FLEXMEASURES_API_TRIGGER_RATE_LIMIT", "1 per 5 minutes"
    )
    sensor = add_battery_assets["Test battery"].sensors[0]
    # Ask for a new job, so that an identical job cached by an earlier test cannot be reused,
    # which would leave the queue length unchanged and tell us nothing.
    message = message_for_trigger_schedule() | {"force-new-job-creation": True}
    scheduling_queue = app.queues["scheduling"]
    queue_length_before = len(scheduling_queue)

    with app.test_client() as client:
        assert trigger(client, sensor.id, message).status_code == 200

        # The accepted trigger queued a scheduling job
        assert len(scheduling_queue) == queue_length_before + 1
        queue_length_after_first_trigger = len(scheduling_queue)

        response = trigger(client, sensor.id, message)

    assert response.status_code == 429
    assert response.json["status"] == "TOO_MANY_REQUESTS"

    # The rate-limited trigger did no work
    assert len(scheduling_queue) == queue_length_after_first_trigger


@pytest.mark.parametrize(
    "rate_limit_key, expected_status_code_for_other_sensor",
    [
        # Each asset gets its own budget ...
        ("account+asset", 422),
        # ... unless the whole account or user shares one budget
        ("account", 429),
        ("user", 429),
    ],
)
@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_trigger_rate_limit_key(
    app,
    add_battery_assets,
    rate_limiting,
    requesting_user,
    rate_limit_key,
    expected_status_code_for_other_sensor,
):
    """The host decides whether the trigger limit is counted per asset, per account or per user."""
    rate_limiting.setitem(app.config, "FLEXMEASURES_API_RATE_LIMIT_KEY", rate_limit_key)
    rate_limiting.setitem(
        app.config, "FLEXMEASURES_API_TRIGGER_RATE_LIMIT", "1 per 5 minutes"
    )
    sensor = add_battery_assets["Test battery"].sensors[0]
    other_sensor = add_battery_assets["Test small battery"].sensors[0]

    with app.test_client() as client:
        assert trigger(client, sensor.id).status_code == 422  # spends the budget
        assert trigger(client, sensor.id).status_code == 429
        response = trigger(client, other_sensor.id)

    assert response.status_code == expected_status_code_for_other_sensor


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_account_can_override_trigger_rate_limit(
    db, app, add_battery_assets, rate_limiting, requesting_user
):
    """An account's own limit takes precedence over the configured default."""
    rate_limiting.setitem(
        app.config, "FLEXMEASURES_API_TRIGGER_RATE_LIMIT", "1 per 5 minutes"
    )
    requesting_user.account.plan = Plan(
        name="test-plan-override", trigger_rate_limit="2 per 5 minutes"
    )
    db.session.commit()
    sensor = add_battery_assets["Test battery"].sensors[0]

    with app.test_client() as client:
        for _ in range(2):
            assert trigger(client, sensor.id).status_code == 422
        assert trigger(client, sensor.id).status_code == 429


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_account_can_be_exempt_from_trigger_rate_limit(
    db, app, add_battery_assets, rate_limiting, requesting_user
):
    """An account can be exempted from a limit altogether."""
    rate_limiting.setitem(
        app.config, "FLEXMEASURES_API_TRIGGER_RATE_LIMIT", "1 per 5 minutes"
    )
    requesting_user.account.plan = Plan(
        name="test-plan-unlimited", trigger_rate_limit="unlimited"
    )
    db.session.commit()
    sensor = add_battery_assets["Test battery"].sensors[0]

    with app.test_client() as client:
        for _ in range(3):
            assert trigger(client, sensor.id).status_code == 422


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_plan_rate_limit_key_overrides_config(
    db, app, add_battery_assets, rate_limiting, requesting_user
):
    """A plan's rate_limit_key takes precedence over the server-wide config setting."""
    rate_limiting.setitem(
        app.config, "FLEXMEASURES_API_RATE_LIMIT_KEY", "account+asset"
    )
    rate_limiting.setitem(
        app.config, "FLEXMEASURES_API_TRIGGER_RATE_LIMIT", "1 per 5 minutes"
    )
    requesting_user.account.plan = Plan(
        name="test-plan-key", rate_limit_key=RateLimitKey.ACCOUNT
    )
    db.session.commit()
    sensor = add_battery_assets["Test battery"].sensors[0]
    other_sensor = add_battery_assets["Test small battery"].sensors[0]

    with app.test_client() as client:
        assert trigger(client, sensor.id).status_code == 422  # spends the budget
        # The account-level key means the other sensor shares the same budget
        assert trigger(client, other_sensor.id).status_code == 429


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_invalid_rate_limit_key_falls_back_instead_of_erroring(
    app, add_battery_assets, rate_limiting, requesting_user
):
    """A bad FLEXMEASURES_API_RATE_LIMIT_KEY must not turn every request into a 500."""
    rate_limiting.setitem(
        app.config, "FLEXMEASURES_API_RATE_LIMIT_KEY", "not-a-real-key"
    )
    rate_limiting.setitem(
        app.config, "FLEXMEASURES_API_TRIGGER_RATE_LIMIT", "1 per 5 minutes"
    )
    sensor = add_battery_assets["Test battery"].sensors[0]

    with app.test_client() as client:
        assert trigger(client, sensor.id).status_code == 422
