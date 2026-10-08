"""Tests for the automations endpoints (GET /api/v3_0/assets/<id>/automations[/<automation-id>])."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from flask import url_for
from redis.exceptions import TimeoutError as RedisTimeoutError
from sqlalchemy import func, select

from flexmeasures.data.models.automations import Automation
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.time_series import Sensor

# Tests here share one database, so the rows each test adds are deleted afterwards.
pytestmark = pytest.mark.usefixtures("undo_new_rows")


def _with_sensor(parameters: dict, sensor_id: int) -> dict:
    """Fill in the sensor id that a parametrised payload leaves as "SENSOR".

    The id only exists once the fixtures have run, which is after the parameters are written.
    """
    return json.loads(json.dumps(parameters).replace('"SENSOR"', str(sensor_id)))


@pytest.mark.parametrize(
    "requesting_user, expected_status_code",
    [
        (None, 401),  # not logged in
        ("test_prosumer_user@seita.nl", 200),  # same account
        ("test_dummy_user_3@seita.nl", 403),  # different account
    ],
    indirect=["requesting_user"],
)
def test_get_automations_auth(
    app,
    add_battery_assets,
    add_automations,
    requesting_user,
    expected_status_code,
):
    battery = add_battery_assets["Test battery"]
    with app.test_client() as client:
        response = client.get(
            url_for("AssetAPI:get_automations", id=battery.id),
        )
    assert response.status_code == expected_status_code


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_get_automations(
    app,
    add_battery_assets,
    add_automations,
    requesting_user,
    mocker,
):
    battery = add_battery_assets["Test battery"]
    mocker.patch(
        "flexmeasures.data.models.automations.server_now",
        return_value=datetime(2026, 7, 11, 3, 30, tzinfo=timezone.utc),
    )
    with app.test_client() as client:
        response = client.get(
            url_for("AssetAPI:get_automations", id=battery.id),
        )
    assert response.status_code == 200
    automations = response.json["automations"]
    assert len(automations) == 2
    day_ahead = next(a for a in automations if a["name"] == "Day-ahead forecasts")
    assert day_ahead["type"] == "forecasting"
    assert day_ahead["cron"] == "0 6 * * *"
    assert day_ahead["timezone"] == "Europe/Amsterdam"
    assert day_ahead["cursor"] == "2026-07-11T06:00:00+02:00"
    assert day_ahead["next-run"] == "2026-07-11T06:00:00+02:00"
    assert day_ahead["recurrence-description"] == "At 06:00"
    assert day_ahead["schedule-revision"] == 1
    assert day_ahead["active"] is True
    assert day_ahead["created-at"] is not None
    intraday = next(a for a in automations if a["name"] == "Intraday forecasts")
    assert intraday["next-run"] is None
    assert day_ahead["job-stats"] == {}  # this automation has not queued any jobs
    # generator and parameters are not listed
    assert "generator_id" not in day_ahead
    assert "source" not in day_ahead
    assert "parameters" not in day_ahead


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_get_automations_when_redis_times_out(
    app,
    add_battery_assets,
    add_automations,
    requesting_user,
    monkeypatch,
):
    """The automation list remains available when Redis times out."""
    battery = add_battery_assets["Test battery"]

    def raise_redis_timeout(asset):
        raise RedisTimeoutError("Redis timed out at private-host.example")

    monkeypatch.setattr(
        "flexmeasures.api.v3_0.assets.get_asset_automations_job_stats",
        raise_redis_timeout,
    )

    with app.test_client() as client:
        response = client.get(url_for("AssetAPI:get_automations", id=battery.id))

    assert response.status_code == 200
    assert len(response.json["automations"]) == 2
    assert all(
        automation["job-stats"] == {} for automation in response.json["automations"]
    )
    assert response.json["redis-connection-err"] == (
        "Redis is unavailable; job statistics could not be loaded."
    )
    assert "private-host.example" not in response.text


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_get_automation_details(
    app,
    add_battery_assets,
    add_automations,
    requesting_user,
    mocker,
):
    battery = add_battery_assets["Test battery"]
    automation = add_automations[0]
    mocker.patch(
        "flexmeasures.data.models.automations.server_now",
        return_value=datetime(2026, 7, 11, 3, 30, tzinfo=timezone.utc),
    )
    with app.test_client() as client:
        response = client.get(
            url_for(
                "AssetAPI:get_automation",
                id=battery.id,
                automation_id=automation.id,
            ),
        )
    assert response.status_code == 200
    assert response.json["name"] == "Day-ahead forecasts"
    assert response.json["timezone"] == "Europe/Amsterdam"
    assert response.json["cursor"] == "2026-07-11T06:00:00+02:00"
    assert response.json["next-run"] == "2026-07-11T06:00:00+02:00"
    assert response.json["schedule-revision"] == 1
    assert response.json["parameters"] == {"sensor": battery.sensors[0].id}
    run_stats = response.json["run-stats"]
    assert run_stats["total"] == 1
    assert run_stats["dispatch"] == {"partially_queued": 1}
    assert run_stats["execution"] == {"pending": 1}
    assert run_stats["latest-run"]["dispatch-state"] == "partially_queued"
    assert run_stats["latest-run"]["attempt-count"] == 2
    assert run_stats["latest-run"]["queued-job-count"] == 1
    assert run_stats["latest-run"]["last-error"] == {
        "type": "ConnectionError",
        "message": "lost Redis connection",
    }
    assert [job["logical-job-key"] for job in run_stats["latest-run"]["jobs"]] == [
        "cycle-001",
        "wrap-up",
    ]
    assert response.json["job-stats"] == {}  # this automation has not queued any jobs
    # the sensor to forecast is both read from (its history) and written to
    sensor = {"id": battery.sensors[0].id, "name": battery.sensors[0].name}
    assert response.json["input-sensors"] == [sensor]
    assert response.json["output-sensors"] == [sensor]


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_get_automation_details_distinguishes_run_outcomes(
    app,
    add_battery_assets,
    add_automations,
    requesting_user,
):
    """An operator can tell a pre-queue failure, a completed dispatch and its execution outcome apart."""
    battery = add_battery_assets["Test battery"]
    automation = add_automations[1]
    with app.test_client() as client:
        response = client.get(
            url_for(
                "AssetAPI:get_automation",
                id=battery.id,
                automation_id=automation.id,
            ),
        )
    assert response.status_code == 200
    run_stats = response.json["run-stats"]
    assert run_stats["total"] == 2
    assert run_stats["dispatch"] == {"failed": 1, "queued": 1}
    assert run_stats["execution"] == {"pending": 1, "succeeded": 1}

    # The most recent occurrence failed before it queued anything, so it can be retried in full.
    latest_run = run_stats["latest-run"]
    assert latest_run["scheduled-at"] == "2026-07-11T05:00:00+00:00"
    assert latest_run["dispatch-state"] == "failed"
    assert latest_run["intended-job-count"] == 0
    assert latest_run["queued-job-count"] == 0
    assert latest_run["first-enqueued-at"] is None
    assert latest_run["last-error"] == {
        "type": "ValidationError",
        "message": "forecast output sensor no longer exists",
    }
    assert latest_run["latest-attempt"]["attempt-no"] == 1
    assert latest_run["latest-attempt"]["outcome"] == "failed"

    # The earlier occurrence needed a retry, finished queueing, and its jobs then succeeded.
    retried_run = run_stats["recent-runs"][1]
    assert retried_run["scheduled-at"] == "2026-07-11T04:00:00+00:00"
    assert retried_run["dispatch-state"] == "queued"
    assert retried_run["execution-state"] == "succeeded"
    assert retried_run["attempt-count"] == 2
    assert retried_run["dispatch-completed-at"] == "2026-07-11T04:02:00+00:00"
    assert retried_run["execution-completed-at"] == "2026-07-11T04:09:00+00:00"
    assert retried_run["latest-attempt"]["attempt-no"] == 2
    assert retried_run["latest-attempt"]["owner"] == "runner-b:2"
    assert retried_run["latest-attempt"]["outcome"] == "queued"
    assert retried_run["latest-attempt"]["error"] is None
    assert [job["status"] for job in retried_run["jobs"]] == ["succeeded"]


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_get_automation_of_other_asset(
    app,
    add_battery_assets,
    add_automations,
    requesting_user,
):
    """Requesting an automation via an asset it does not belong to should return 404."""
    other_asset = add_battery_assets["Test small battery"]
    automation = add_automations[0]
    with app.test_client() as client:
        response = client.get(
            url_for(
                "AssetAPI:get_automation",
                id=other_asset.id,
                automation_id=automation.id,
            ),
        )
    assert response.status_code == 404


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_get_nonexistent_automation(
    app,
    add_battery_assets,
    add_automations,
    requesting_user,
):
    battery = add_battery_assets["Test battery"]
    with app.test_client() as client:
        response = client.get(
            url_for("AssetAPI:get_automation", id=battery.id, automation_id=9999),
        )
    assert response.status_code == 404


@pytest.mark.parametrize(
    "requesting_user, expected_status_code",
    [
        ("test_prosumer_user@seita.nl", 201),  # plain account member
        ("test_prosumer_user_2@seita.nl", 201),  # account admin
        ("test_dummy_user_3@seita.nl", 403),  # different account
    ],
    indirect=["requesting_user"],
)
def test_post_automation(
    app,
    db,
    add_battery_assets,
    requesting_user,
    expected_status_code,
):
    """Whoever may add data under the asset can create automations on it; parameters are validated by type."""
    battery = add_battery_assets["Test battery"]
    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:post_automation", id=battery.id),
            json={
                "name": "Posted schedules",
                "cron": "0 0 * * *",
                "type": "scheduling",
                "parameters": {"duration": "PT12H"},
            },
        )
    assert response.status_code == expected_status_code
    if expected_status_code == 201:
        assert response.json["name"] == "Posted schedules"
        assert response.json["active"] is True
        assert response.json["recurrence-description"] == "At 00:00"
        automation = db.session.get(Automation, response.json["id"])
        assert automation.parameters == {"duration": "PT12H"}


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user_2@seita.nl"], indirect=True
)
def test_post_automation_with_foreign_sensor(
    app,
    db,
    setup_accounts,
    add_battery_assets,
    requesting_user,
):
    """Referencing a sensor outside the caller's reach is forbidden."""
    from datetime import timedelta

    from flexmeasures.data.models.generic_assets import GenericAsset
    from flexmeasures.data.models.time_series import Sensor

    battery = add_battery_assets["Test battery"]
    foreign_asset = GenericAsset(
        name="Foreign asset",
        generic_asset_type=battery.generic_asset_type,
        owner=setup_accounts["Dummy"],
    )
    foreign_sensor = Sensor(
        "foreign power",
        generic_asset=foreign_asset,
        event_resolution=timedelta(minutes=15),
        unit="MW",
    )
    db.session.add(foreign_sensor)
    db.session.commit()
    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:post_automation", id=battery.id),
            json={
                "name": "Sneaky forecasts",
                "cron": "0 6 * * *",
                "type": "forecasting",
                "parameters": {"sensor": foreign_sensor.id},
            },
        )
    assert response.status_code == 403
    assert (
        db.session.execute(
            select(Automation).filter_by(name="Sneaky forecasts")
        ).scalar_one_or_none()
        is None
    )


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user_2@seita.nl"], indirect=True
)
def test_post_report_automation_with_foreign_config_sensor(
    app,
    db,
    setup_accounts,
    add_battery_assets,
    requesting_user,
):
    """Reporter configuration may not read a sensor outside the caller's reach."""
    from flexmeasures.data.models.generic_assets import GenericAsset

    battery = add_battery_assets["Test battery"]
    foreign_asset = GenericAsset(
        name="Foreign price asset",
        generic_asset_type=battery.generic_asset_type,
        owner=setup_accounts["Dummy"],
    )
    foreign_price_sensor = Sensor(
        "private foreign price",
        generic_asset=foreign_asset,
        event_resolution=timedelta(hours=1),
        unit="EUR/MWh",
    )
    report_sensor = Sensor(
        "profit report",
        generic_asset=battery,
        event_resolution=timedelta(hours=1),
        unit="EUR",
    )
    db.session.add_all([foreign_price_sensor, report_sensor])
    db.session.commit()

    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:post_automation", id=battery.id),
            json={
                "name": "Cross-organisation profit report",
                "cron": "0 1 * * *",
                "type": "reporting",
                "data-generator": "ProfitOrLossReporter",
                "config": {
                    "consumption_price_sensor": foreign_price_sensor.id,
                },
                "parameters": {
                    "input": [{"sensor": battery.sensors[0].id}],
                    "output": [{"sensor": report_sensor.id}],
                },
            },
        )

    assert response.status_code == 403
    assert foreign_price_sensor.name not in response.text
    assert (
        db.session.execute(
            select(Automation).filter_by(name="Cross-organisation profit report")
        ).scalar_one_or_none()
        is None
    )
    db.session.commit()


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user_2@seita.nl"], indirect=True
)
def test_post_report_automation_rejects_output_outside_asset_subtree(
    app,
    db,
    add_battery_assets,
    requesting_user,
):
    """Report output must stay on the automation asset or a descendant."""
    battery = add_battery_assets["Test battery"]
    sibling_battery = add_battery_assets["Test small battery"]
    report_sensor = Sensor(
        "sibling report output",
        generic_asset=sibling_battery,
        event_resolution=timedelta(hours=1),
        unit="MW",
    )
    db.session.add(report_sensor)
    db.session.commit()

    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:post_automation", id=battery.id),
            json={
                "name": "Misplaced report output",
                "cron": "0 1 * * *",
                "type": "reporting",
                "data-generator": "PandasReporter",
                "config": {
                    "required_input": [{"name": "flow"}],
                    "required_output": [{"name": "copied_flow"}],
                    "transformations": [
                        {
                            "df_input": "flow",
                            "df_output": "copied_flow",
                            "method": "copy",
                        }
                    ],
                },
                "parameters": {
                    "input": [{"name": "flow", "sensor": battery.sensors[0].id}],
                    "output": [{"name": "copied_flow", "sensor": report_sensor.id}],
                },
            },
        )

    assert response.status_code == 422
    assert "must belong to asset" in response.text
    db.session.commit()


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user_2@seita.nl"], indirect=True
)
def test_post_automation_with_invalid_parameters(
    app,
    add_battery_assets,
    requesting_user,
):
    battery = add_battery_assets["Test battery"]
    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:post_automation", id=battery.id),
            json={
                "name": "Bad forecasts",
                "cron": "0 6 * * *",
                "type": "forecasting",
                "parameters": {},  # missing required sensor
            },
        )
    assert response.status_code == 422
    assert "sensor" in str(response.json)


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user_2@seita.nl"], indirect=True
)
def test_post_and_patch_automation_timezone(
    app,
    db,
    add_battery_assets,
    requesting_user,
):
    """An automation's timezone can be set on creation and changed afterwards, as it can from the CLI."""
    battery = add_battery_assets["Test battery"]
    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:post_automation", id=battery.id),
            json={
                "name": "Seoul forecasts",
                "cron": "0 6 * * *",
                "timezone": "Asia/Seoul",
                "type": "forecasting",
                "parameters": {"sensor": battery.sensors[0].id},
            },
        )
    assert response.status_code == 201, response.json
    assert response.json["timezone"] == "Asia/Seoul"
    automation = db.session.execute(
        select(Automation).filter_by(name="Seoul forecasts")
    ).scalar_one()
    assert automation.timezone == "Asia/Seoul"

    with app.test_client() as client:
        response = client.patch(
            url_for(
                "AssetAPI:patch_automation",
                id=battery.id,
                automation_id=automation.id,
            ),
            json={"timezone": "Europe/Amsterdam"},
        )
    assert response.status_code == 200, response.json
    assert response.json["timezone"] == "Europe/Amsterdam"
    assert automation.timezone == "Europe/Amsterdam"

    with app.test_client() as client:
        response = client.patch(
            url_for(
                "AssetAPI:patch_automation",
                id=battery.id,
                automation_id=automation.id,
            ),
            json={"timezone": "Europe/NotAmsterdam"},
        )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user_2@seita.nl"], indirect=True
)
def test_post_automation_with_inaccessible_source_filtered_regressor(
    app,
    db,
    add_battery_assets,
    setup_generic_assets,
    requesting_user,
):
    """A regressor that filters on sources is a sensor reference, and still counts as a sensor read."""
    battery = add_battery_assets["Test battery"]
    someone_elses_sensor = Sensor(
        name="wind speed for a filtered regressor",
        generic_asset=setup_generic_assets[
            "test_wind_turbine"
        ],  # owned by the Supplier account
        event_resolution=timedelta(minutes=15),
        unit="m/s",
    )
    db.session.add(someone_elses_sensor)
    db.session.commit()
    data_sources_before = set(db.session.scalars(select(DataSource.id)).all())

    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:post_automation", id=battery.id),
            json={
                "name": "Forecasts regressing on another account's sensor",
                "cron": "0 6 * * *",
                "type": "forecasting",
                "parameters": {"sensor": battery.sensors[0].id},
                "config": {
                    "regressors": [
                        {
                            "sensor": someone_elses_sensor.id,
                            "source-types": ["forecaster"],
                        }
                    ]
                },
            },
        )
    assert response.status_code == 403
    assert str(someone_elses_sensor.id) in response.json["message"]
    assert someone_elses_sensor.name not in response.json["message"]
    assert (
        db.session.execute(
            select(Automation).filter_by(
                name="Forecasts regressing on another account's sensor"
            )
        ).scalar_one_or_none()
        is None
    )
    # a refused request also leaves behind no data source for the forecaster it would have run
    assert set(db.session.scalars(select(DataSource.id)).all()) == data_sources_before


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user_2@seita.nl"], indirect=True
)
def test_post_automation_with_inaccessible_sensor(
    app,
    db,
    add_battery_assets,
    setup_generic_assets,
    requesting_user,
):
    """An account admin cannot set up an automation on a sensor of another account."""
    battery = add_battery_assets["Test battery"]
    someone_elses_sensor = Sensor(
        name="wind speed",
        generic_asset=setup_generic_assets[
            "test_wind_turbine"
        ],  # owned by the Supplier account
        event_resolution=timedelta(minutes=15),
        unit="m/s",
    )
    db.session.add(someone_elses_sensor)
    db.session.commit()

    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:post_automation", id=battery.id),
            json={
                "name": "Forecasts of another account's sensor",
                "cron": "0 6 * * *",
                "type": "forecasting",
                "parameters": {"sensor": someone_elses_sensor.id},
            },
        )
    assert response.status_code == 403
    assert str(someone_elses_sensor.id) in response.json["message"]
    assert someone_elses_sensor.name not in response.json["message"]
    assert (
        db.session.execute(
            select(Automation).filter_by(name="Forecasts of another account's sensor")
        ).scalar_one_or_none()
        is None
    )

    # the same automation on their own sensor is fine
    own_sensor = battery.sensors[0]
    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:post_automation", id=battery.id),
            json={
                "name": "Forecasts of their own sensor",
                "cron": "0 6 * * *",
                "type": "forecasting",
                "parameters": {"sensor": own_sensor.id},
            },
        )
    assert response.status_code == 201, response.json


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user_2@seita.nl"], indirect=True
)
def test_post_schedule_automation_with_inaccessible_output_sensor(
    app,
    db,
    add_battery_assets,
    setup_generic_assets,
    requesting_user,
):
    """Sensors that a schedule would be recorded on are checked, wherever they are named.

    The aggregate power schedule is recorded on the flex-context's aggregate-consumption sensor,
    so that one needs to be writable, too, not just the flex-model's own sensors.
    """
    battery = add_battery_assets["Test battery"]
    someone_elses_sensor = Sensor(
        name="aggregate consumption",
        generic_asset=setup_generic_assets[
            "test_wind_turbine"
        ],  # owned by the Supplier account
        event_resolution=timedelta(minutes=15),
        unit="MW",
    )
    db.session.add(someone_elses_sensor)
    db.session.commit()

    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:post_automation", id=battery.id),
            json={
                "name": "Schedules aggregated onto another account's sensor",
                "cron": "0 0 * * *",
                "type": "scheduling",
                "parameters": {
                    "duration": "PT12H",
                    "flex-context": {
                        "aggregate-consumption": {"sensor": someone_elses_sensor.id}
                    },
                },
            },
        )
    assert response.status_code == 403
    assert str(someone_elses_sensor.id) in response.json["message"]
    assert someone_elses_sensor.name not in response.json["message"]
    assert "record data on" in response.json["message"]


@pytest.mark.parametrize(
    "requesting_user, expected_status_code",
    [
        ("test_prosumer_user@seita.nl", 200),  # plain account member
        ("test_prosumer_user_2@seita.nl", 200),  # account admin
    ],
    indirect=["requesting_user"],
)
def test_patch_automation(
    app,
    db,
    add_battery_assets,
    add_automations,
    requesting_user,
    expected_status_code,
):
    battery = add_battery_assets["Test battery"]
    automation = add_automations[0]
    original_name = automation.name
    try:
        with app.test_client() as client:
            response = client.patch(
                url_for(
                    "AssetAPI:patch_automation",
                    id=battery.id,
                    automation_id=automation.id,
                ),
                json={"name": "Renamed via API", "active": False},
            )
        assert response.status_code == expected_status_code
        if expected_status_code == 200:
            assert response.json["name"] == "Renamed via API"
            assert response.json["active"] is False
    finally:
        # restore for other tests in this module
        db.session.rollback()
        automation.name = original_name
        automation.active = True
        db.session.commit()


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user_2@seita.nl"], indirect=True
)
def test_delete_automation(
    app,
    db,
    add_battery_assets,
    add_automations,
    requesting_user,
):
    battery = add_battery_assets["Test battery"]
    automation = Automation(
        asset_id=battery.id,
        # a forecast automation is required to have a data generator holding its forecaster config
        generator=add_automations[0].generator,
        type="forecasting",
        name="To be deleted",
        cronstr="0 6 * * *",
        parameters={"sensor": battery.sensors[0].id},
    )
    db.session.add(automation)
    db.session.commit()
    with app.test_client() as client:
        response = client.delete(
            url_for(
                "AssetAPI:delete_automation",
                id=battery.id,
                automation_id=automation.id,
            ),
        )
        assert response.status_code == 204
        assert db.session.get(Automation, automation.id) is None

        # deleting again yields the documented 404
        response = client.delete(
            url_for(
                "AssetAPI:delete_automation",
                id=battery.id,
                automation_id=automation.id,
            ),
        )
        assert response.status_code == 404


@pytest.mark.parametrize(
    "requesting_user, expected_status_code",
    [
        (None, 401),  # not logged in
        ("test_prosumer_user@seita.nl", 202),  # same account
        ("test_dummy_user_3@seita.nl", 403),  # different account
    ],
    indirect=["requesting_user"],
)
def test_trigger_automation_auth(
    app,
    add_battery_assets,
    add_automations,
    requesting_user,
    expected_status_code,
    mocker,
):
    battery = add_battery_assets["Test battery"]
    automation = add_automations[0]
    run_automation = mocker.patch(
        "flexmeasures.api.v3_0.assets.run_automation",
        return_value={"job_id": "364bfd06-c1fa-430b-8d25-8f5a547651fb", "n_jobs": 2},
    )
    with app.test_client() as client:
        response = client.post(
            url_for(
                "AssetAPI:trigger_automation",
                id=battery.id,
                automation_id=automation.id,
            ),
        )
    assert response.status_code == expected_status_code
    if expected_status_code == 202:
        assert run_automation.call_args.args[0].id == automation.id
    else:
        run_automation.assert_not_called()


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_trigger_automation(
    app,
    db,
    add_battery_assets,
    add_automations,
    requesting_user,
    mocker,
):
    """Triggering a run reports the queued job, and leaves the automation's recurrence alone."""
    battery = add_battery_assets["Test battery"]
    automation = add_automations[1]  # inactive automations can be triggered, too.
    cursor_before = automation.cursor
    mocker.patch(
        "flexmeasures.api.v3_0.assets.run_automation",
        return_value={"job_id": "364bfd06-c1fa-430b-8d25-8f5a547651fb", "n_jobs": 2},
    )
    with app.test_client() as client:
        response = client.post(
            url_for(
                "AssetAPI:trigger_automation",
                id=battery.id,
                automation_id=automation.id,
            ),
        )
    assert response.status_code == 202
    assert response.json["status"] == "ACCEPTED"
    assert response.json["job"] == "364bfd06-c1fa-430b-8d25-8f5a547651fb"
    assert response.json["n-jobs"] == 2
    db.session.expire_all()
    assert automation.cursor == cursor_before
    assert automation.active is False


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_trigger_automation_that_cannot_run(
    app,
    add_battery_assets,
    add_automations,
    requesting_user,
    mocker,
):
    """A run which cannot be set up is reported as such, rather than as a queued job."""
    battery = add_battery_assets["Test battery"]
    automation = add_automations[0]
    mocker.patch(
        "flexmeasures.api.v3_0.assets.run_automation",
        side_effect=ValueError(
            "Forecast automation output sensor 3 must belong to asset 1 or one of its descendants."
        ),
    )
    with app.test_client() as client:
        response = client.post(
            url_for(
                "AssetAPI:trigger_automation",
                id=battery.id,
                automation_id=automation.id,
            ),
        )
    assert response.status_code == 422
    assert "must belong to asset" in str(response.json["message"])


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
@pytest.mark.parametrize("via_other_asset", [True, False])
def test_trigger_unknown_automation(
    app,
    add_battery_assets,
    add_automations,
    requesting_user,
    via_other_asset,
    mocker,
):
    """Triggering an automation the asset does not have returns 404, without running anything."""
    run_automation = mocker.patch("flexmeasures.api.v3_0.assets.run_automation")
    if via_other_asset:
        # an existing automation, requested through an asset it does not belong to.
        asset = add_battery_assets["Test small battery"]
        automation_id = add_automations[0].id
    else:
        asset = add_battery_assets["Test battery"]
        automation_id = 9999
    with app.test_client() as client:
        response = client.post(
            url_for(
                "AssetAPI:trigger_automation",
                id=asset.id,
                automation_id=automation_id,
            ),
        )
    assert response.status_code == 404
    run_automation.assert_not_called()


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_creating_an_automation_whose_sensors_are_unknown_is_the_callers_fault(
    app, add_battery_assets, requesting_user, mocker
):
    """A scheduler that cannot work out its config answers 422, not 500.

    `create_automation` raises `AutomationSensorsUnknown`, which is not a `ValueError`,
    so it would otherwise leave the endpoint uncaught.
    """
    from flexmeasures.data.services.automations import AutomationSensorsUnknown

    mocker.patch(
        "flexmeasures.api.v3_0.assets.create_automation",
        side_effect=AutomationSensorsUnknown("no sensors to be had"),
    )
    battery = add_battery_assets["Test battery"]
    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:post_automation", id=battery.id),
            json={
                "name": "Unknowable",
                "cron": "0 6 * * *",
                "type": "scheduling",
                "parameters": {"duration": "PT12H"},
            },
        )

    assert response.status_code == 422, response.json
    assert "no sensors to be had" in str(response.json)


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_a_forecast_automation_names_the_data_generator_it_runs(
    app, db, add_battery_assets, requesting_user
):
    """The class a forecast automation runs is chosen by `data-generator`, and the response names the source it resolved to.

    The request names a class; the response names the data source that class was set up as,
    which is why the two are not the same field.
    """
    battery = add_battery_assets["Test battery"]
    sensor = battery.sensors[0]
    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:post_automation", id=battery.id),
            json={
                "name": "Named generator",
                "cron": "0 6 * * *",
                "type": "forecasting",
                "data-generator": "TrainPredictPipeline",
                "parameters": {"sensor": sensor.id},
            },
        )

    assert response.status_code == 201, response.json
    automation = db.session.get(Automation, response.json["id"])
    assert automation.generator.model == "TrainPredictPipeline"

    detail = client.get(
        url_for("AssetAPI:get_automation", id=battery.id, automation_id=automation.id)
    )
    assert detail.status_code == 200, detail.json
    assert detail.json["source"]["id"] == automation.generator_id


@pytest.mark.parametrize(
    "automation_type, data_generator, config, parameters",
    [
        (
            "forecasting",
            "TrainPredictPipeline",
            {"not-a-config-field": 1},
            {"sensor": "SENSOR"},
        ),
        (
            "reporting",
            "PandasReporter",
            {
                "required_input": [{"name": "flow"}],
                "required_output": [{"name": "flow"}],
                "transformations": [],
                "not-a-config-field": 1,
            },
            {
                "input": [{"name": "flow", "sensor": "SENSOR"}],
                "output": [{"name": "flow", "sensor": "SENSOR"}],
            },
        ),
    ],
)
@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user_2@seita.nl"], indirect=True
)
def test_post_automation_reports_a_config_error_against_the_config(
    app,
    add_battery_assets,
    requesting_user,
    automation_type,
    data_generator,
    config,
    parameters,
):
    """A fault in the data generator's config is reported against `config`, not against `parameters`.

    Both are validated by schemas of the data generator's choosing, so naming the wrong one
    sends the caller looking for a mistake in a part of the request that is fine.
    """
    battery = add_battery_assets["Test battery"]
    sensor_id = battery.sensors[0].id
    parameters = _with_sensor(parameters, sensor_id)

    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:post_automation", id=battery.id),
            json={
                "name": "Bad config",
                "cron": "0 6 * * *",
                "type": automation_type,
                "data-generator": data_generator,
                "config": config,
                "parameters": parameters,
            },
        )

    assert response.status_code == 422, response.json
    messages = response.json["message"]["json"]
    assert "not-a-config-field" in str(messages["config"])
    assert "parameters" not in messages


@pytest.mark.parametrize(
    "automation_type, data_generator, config, parameters",
    [
        (
            "forecasting",
            "TrainPredictPipeline",
            {},
            {"sensor": "SENSOR", "not-a-parameter": 1},
        ),
        (
            "reporting",
            "PandasReporter",
            {
                "required_input": [{"name": "flow"}],
                "required_output": [{"name": "flow"}],
                "transformations": [],
            },
            {
                "input": [{"name": "flow", "sensor": "SENSOR"}],
                "output": [{"name": "flow", "sensor": "SENSOR"}],
                "not-a-parameter": 1,
            },
        ),
        ("scheduling", None, {}, {"duration": "PT12H", "not-a-parameter": 1}),
    ],
)
@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user_2@seita.nl"], indirect=True
)
def test_post_automation_reports_a_parameter_error_against_the_parameters(
    app,
    add_battery_assets,
    requesting_user,
    automation_type,
    data_generator,
    config,
    parameters,
):
    """A fault in the parameters is reported against `parameters`, for every automation type."""
    battery = add_battery_assets["Test battery"]
    parameters = _with_sensor(parameters, battery.sensors[0].id)
    payload = {
        "name": "Bad parameters",
        "cron": "0 6 * * *",
        "type": automation_type,
        "parameters": parameters,
    }
    if data_generator is not None:
        payload["data-generator"] = data_generator
        payload["config"] = config

    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:post_automation", id=battery.id), json=payload
        )

    assert response.status_code == 422, response.json
    messages = response.json["message"]["json"]
    assert "not-a-parameter" in str(messages["parameters"])
    assert "config" not in messages


@pytest.mark.parametrize(
    "field, value",
    [
        ("config", {"model": "CustomLGBM"}),
        ("data-generator", "TrainPredictPipeline"),
    ],
)
@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user_2@seita.nl"], indirect=True
)
def test_post_schedule_automation_rejects_a_data_generator_and_its_config(
    app, db, add_battery_assets, requesting_user, field, value
):
    """A schedule automation resolves its own scheduler and flex config from the asset.

    Taking either field here would record a choice that nothing goes on to read,
    so each is refused by name rather than silently ignored.
    """
    battery = add_battery_assets["Test battery"]
    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:post_automation", id=battery.id),
            json={
                "name": "Schedules with an unusable field",
                "cron": "0 6 * * *",
                "type": "scheduling",
                "parameters": {"duration": "PT12H"},
                field: value,
            },
        )

    assert response.status_code == 422, response.json
    assert field in response.json["message"]["json"]
    assert (
        db.session.execute(
            select(Automation).filter_by(name="Schedules with an unusable field")
        ).scalar_one_or_none()
        is None
    )


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user_2@seita.nl"], indirect=True
)
def test_post_report_automation_without_a_reporter_names_the_field_to_fill_in(
    app, add_battery_assets, requesting_user
):
    """A report automation has to name its reporter, and the error says which field is missing."""
    battery = add_battery_assets["Test battery"]
    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:post_automation", id=battery.id),
            json={
                "name": "Reporter-less report",
                "cron": "0 1 * * *",
                "type": "reporting",
                "parameters": {"input": [{"sensor": battery.sensors[0].id}]},
            },
        )

    assert response.status_code == 422, response.json
    assert "A reporter is required" in str(
        response.json["message"]["json"]["data-generator"]
    )


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user_2@seita.nl"], indirect=True
)
def test_a_refused_automation_leaves_nothing_behind(
    app, db, add_battery_assets, requesting_user
):
    """A rejected request records neither the automation, nor a data source for its generator, nor an audit log entry."""
    from flexmeasures.data.models.audit_log import AssetAuditLog

    battery = add_battery_assets["Test battery"]
    sensor_id = battery.sensors[0].id
    before = {
        model: db.session.scalar(select(func.count()).select_from(model))
        for model in (Automation, DataSource, AssetAuditLog)
    }
    refused = [
        {
            "type": "forecasting",
            "config": {"not-a-config-field": 1},
            "parameters": {"sensor": sensor_id},
        },
        {
            "type": "forecasting",
            "parameters": {"sensor": sensor_id, "not-a-parameter": 1},
        },
        {
            "type": "scheduling",
            "data-generator": "TrainPredictPipeline",
            "parameters": {"duration": "PT12H"},
        },
    ]
    with app.test_client() as client:
        for index, payload in enumerate(refused):
            response = client.post(
                url_for("AssetAPI:post_automation", id=battery.id),
                json={"name": f"Refused {index}", "cron": "0 6 * * *", **payload},
            )
            assert response.status_code == 422, response.json

    after = {
        model: db.session.scalar(select(func.count()).select_from(model))
        for model in (Automation, DataSource, AssetAuditLog)
    }
    assert after == before


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_automation_details_report_the_data_source_configuration(
    app, db, add_battery_assets, requesting_user
):
    """The config is what separates one data source from another of the same model, so it is reported with it."""
    battery = add_battery_assets["Test battery"]
    generator = DataSource(
        name="configured generator",
        type="forecaster",
        model="TrainPredictPipeline",
        attributes={
            "data_generator": {
                "config": {"model": "CustomLGBM", "train-period": "P30D"}
            }
        },
    )
    automation = Automation(
        asset_id=battery.id,
        generator=generator,
        type="forecasting",
        name="Configured forecasts",
        cronstr="0 6 * * *",
        timezone="Europe/Amsterdam",
        active=True,
        parameters={"sensor": battery.sensors[0].id},
    )
    db.session.add(automation)
    db.session.commit()
    with app.test_client() as client:
        response = client.get(
            url_for(
                "AssetAPI:get_automation", id=battery.id, automation_id=automation.id
            )
        )
    assert response.status_code == 200, response.json
    assert response.json["source"]["config"] == {
        "model": "CustomLGBM",
        "train-period": "P30D",
    }
