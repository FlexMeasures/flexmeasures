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
    assert day_ahead["revision"] == 1
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
    assert response.json["revision"] == 1
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
    sensor = {
        "id": battery.sensors[0].id,
        "name": battery.sensors[0].name,
        "readable": True,
    }
    assert response.json["input-sensors"] == [sensor]
    assert response.json["output-sensors"] == [sensor]
    # Set up without a user making the request, as through the CLI, so its runs check nobody's access.
    assert response.json["runs-as"] is None


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
        assert response.json["monitored"] is True
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


@pytest.mark.parametrize("path_field", ["model-save-dir", "output-path"])
@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_post_forecast_automation_refuses_server_paths(
    app, add_battery_assets, requesting_user, path_field, tmp_path
):
    """Server paths to write models or outputs to are for the CLI only, so a forecast automation may not store them."""
    battery = add_battery_assets["Test battery"]
    chosen_dir = tmp_path / "chosen-by-the-client"
    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:post_automation", id=battery.id),
            json={
                "name": "Forecasts kept on the server",
                "cron": "0 6 * * *",
                "type": "forecasting",
                "parameters": {
                    "sensor": battery.sensors[0].id,
                    path_field: str(chosen_dir),
                },
            },
        )
    assert response.status_code == 422, response.json
    assert path_field in str(response.json)
    assert not chosen_dir.exists()


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
def test_post_and_patch_automation_monitoring(
    app,
    db,
    add_battery_assets,
    requesting_user,
):
    """An automation can opt out of monitoring on creation, and opt back in afterwards."""
    from flexmeasures.data.models.audit_log import AssetAuditLog

    battery = add_battery_assets["Test battery"]
    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:post_automation", id=battery.id),
            json={
                "name": "Experimental schedules",
                "cron": "0 0 * * *",
                "type": "scheduling",
                "parameters": {"duration": "PT12H"},
                "monitored": False,
            },
        )
    assert response.status_code == 201, response.json
    assert response.json["monitored"] is False
    automation = db.session.get(Automation, response.json["id"])
    assert automation.monitored is False

    with app.test_client() as client:
        response = client.patch(
            url_for(
                "AssetAPI:patch_automation",
                id=battery.id,
                automation_id=automation.id,
            ),
            json={"monitored": True},
        )
    assert response.status_code == 200, response.json
    assert response.json["monitored"] is True
    assert automation.monitored is True
    assert db.session.scalars(
        select(AssetAuditLog.event).where(
            AssetAuditLog.affected_asset_id == battery.id,
            AssetAuditLog.event.contains("monitoring switched on"),
        )
    ).all()


@pytest.mark.parametrize(
    "requesting_user, may_change_monitoring",
    [
        ("test_admin_user@seita.nl", True),
        (
            "test_prosumer_user_2@seita.nl",
            True,
        ),  # account-admin of the asset's organisation
        (
            "test_prosumer_user@seita.nl",
            False,
        ),  # member, who may manage the automation otherwise
        (
            "test_consultant@seita.nl",
            False,
        ),  # once the asset's organisation is a client of the consultancy
    ],
    indirect=["requesting_user"],
)
def test_only_admins_may_switch_monitoring(
    app,
    db,
    add_battery_assets,
    requesting_user,
    may_change_monitoring,
):
    """Only the host's admins and the asset's account-admins may create an unmonitored automation, or switch monitoring on or off."""
    battery = add_battery_assets["Test battery"]
    owner = battery.owner
    original_consultancy_id = owner.consultancy_account_id
    if requesting_user.has_role("consultant"):
        # Make the consultant one of the organisation's own, so that they may manage its automations.
        owner.consultancy_account_id = requesting_user.account_id
        db.session.commit()
    try:
        _check_who_may_switch_monitoring(app, db, battery, may_change_monitoring)
    finally:
        owner.consultancy_account_id = original_consultancy_id
        db.session.commit()


def _check_who_may_switch_monitoring(app, db, battery, may_change_monitoring: bool):
    automation_data = {
        "name": "Experimental schedules",
        "cron": "0 0 * * *",
        "type": "scheduling",
        "parameters": {"duration": "PT12H"},
    }
    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:post_automation", id=battery.id),
            json={**automation_data, "monitored": False},
        )
    if may_change_monitoring:
        assert response.status_code == 201, response.json
    else:
        assert response.status_code == 403, response.json
        assert "Only admins" in response.json["message"]

    # Anyone who may manage the automation may still create a monitored one, and edit it with the monitoring left as it is.
    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:post_automation", id=battery.id),
            json={**automation_data, "name": "Monitored schedules", "monitored": True},
        )
    assert response.status_code == 201, response.json
    automation = db.session.get(Automation, response.json["id"])
    with app.test_client() as client:
        response = client.patch(
            url_for(
                "AssetAPI:patch_automation",
                id=battery.id,
                automation_id=automation.id,
            ),
            json={"name": "Renamed schedules", "monitored": True},
        )
    assert response.status_code == 200, response.json

    with app.test_client() as client:
        response = client.patch(
            url_for(
                "AssetAPI:patch_automation",
                id=battery.id,
                automation_id=automation.id,
            ),
            json={"monitored": False},
        )
    if may_change_monitoring:
        assert response.status_code == 200, response.json
        assert automation.monitored is False
    else:
        assert response.status_code == 403, response.json
        db.session.refresh(automation)
        assert automation.monitored is True


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


@pytest.mark.parametrize("source_kind", ["account", "asset", "sensor"])
@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user_2@seita.nl"], indirect=True
)
def test_post_forecast_automation_with_inaccessible_annotation_regressor(
    app,
    db,
    add_battery_assets,
    setup_generic_assets,
    setup_accounts,
    requesting_user,
    source_kind,
):
    """Annotations used as a regressor must come from an account, asset or sensor the creator can read."""
    battery = add_battery_assets["Test battery"]
    wind_turbine = setup_generic_assets[
        "test_wind_turbine"
    ]  # owned by the Supplier account
    someone_elses_sensor = Sensor(
        name="annotated sensor",
        generic_asset=wind_turbine,
        event_resolution=timedelta(minutes=15),
        unit="MW",
    )
    db.session.add(someone_elses_sensor)
    db.session.commit()
    source_id = {
        "account": setup_accounts["Supplier"].id,
        "asset": wind_turbine.id,
        "sensor": someone_elses_sensor.id,
    }[source_kind]
    name = f"Forecasts with another account's annotations ({source_kind})"

    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:post_automation", id=battery.id),
            json={
                "name": name,
                "cron": "0 6 * * *",
                "type": "forecasting",
                "parameters": {"sensor": battery.sensors[0].id},
                "config": {"annotation-regressors": [{source_kind: source_id}]},
            },
        )
    assert response.status_code == 403, response.json
    assert f"{source_kind} {source_id}" in response.json["message"]
    assert (
        db.session.execute(select(Automation).filter_by(name=name)).scalar_one_or_none()
        is None
    )

    # Annotations of their own account are fine
    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:post_automation", id=battery.id),
            json={
                "name": f"Forecasts with own annotations ({source_kind})",
                "cron": "0 6 * * *",
                "type": "forecasting",
                "parameters": {"sensor": battery.sensors[0].id},
                "config": {"annotation-regressors": [{"account": battery.owner.id}]},
            },
        )
    assert response.status_code == 201, response.json


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user_2@seita.nl"], indirect=True
)
def test_forecast_automation_run_rechecks_annotation_regressors(
    app,
    db,
    add_battery_assets,
    setup_accounts,
    requesting_user,
):
    """Before each run, the creator must still be able to read the annotations the forecast uses."""
    from werkzeug.exceptions import Forbidden

    from flexmeasures.data.models.generic_assets import GenericAsset
    from flexmeasures.data.services.automations import run_automation

    battery = add_battery_assets["Test battery"]
    annotated_asset = GenericAsset(
        name="Annotated asset",
        generic_asset_type=battery.generic_asset_type,
        owner=battery.owner,
    )
    db.session.add(annotated_asset)
    db.session.commit()

    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:post_automation", id=battery.id),
            json={
                "name": "Forecasts with annotations of an asset that moves away",
                "cron": "0 6 * * *",
                "type": "forecasting",
                "parameters": {"sensor": battery.sensors[0].id},
                "config": {"annotation-regressors": [{"asset": annotated_asset.id}]},
            },
        )
    assert response.status_code == 201, response.json
    automation = db.session.get(Automation, response.json["id"])
    assert automation.execution_user_id == requesting_user.id

    # The annotated asset now belongs to another account, which the creator cannot read
    annotated_asset.owner = setup_accounts["Supplier"]
    db.session.commit()
    with pytest.raises(Forbidden):
        run_automation(automation)


@pytest.mark.parametrize(
    "reference_extras",
    [
        {},
        {"source-types": ["forecaster"]},
        {"exclude-source-types": ["scheduler"]},
        {"default": "30 EUR/MWh"},
        {"lower": 0},
    ],
    ids=["plain", "source-types", "exclude-source-types", "default", "lower"],
)
@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user_2@seita.nl"], indirect=True
)
def test_post_schedule_automation_with_inaccessible_filtered_input_sensor(
    app,
    db,
    add_battery_assets,
    setup_generic_assets,
    requesting_user,
    reference_extras,
):
    """A sensor the schedule reads is checked, also when its reference carries source filters,
    a default or bounds (which deserialize to a SensorReference rather than a Sensor).
    """
    battery = add_battery_assets["Test battery"]
    someone_elses_sensor = Sensor(
        name="someone else's prices",
        generic_asset=setup_generic_assets[
            "test_wind_turbine"
        ],  # owned by the Supplier account
        event_resolution=timedelta(minutes=15),
        unit="EUR/MWh",
    )
    db.session.add(someone_elses_sensor)
    db.session.commit()
    name = f"Schedules on another account's prices {sorted(reference_extras)}"

    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:post_automation", id=battery.id),
            json={
                "name": name,
                "cron": "0 0 * * *",
                "type": "scheduling",
                "parameters": {
                    "duration": "PT12H",
                    "flex-context": {
                        "consumption-price": {
                            "sensor": someone_elses_sensor.id,
                            **reference_extras,
                        }
                    },
                },
            },
        )
    assert response.status_code == 403, response.json
    assert str(someone_elses_sensor.id) in response.json["message"]
    assert (
        db.session.execute(select(Automation).filter_by(name=name)).scalar_one_or_none()
        is None
    )


@pytest.mark.parametrize(
    "model_params, status_code",
    [
        ({"machines": "127.0.0.1:12400,10.0.0.1:12400", "num_machines": 2}, 422),
        ({"num_threads": 64}, 422),
        ({"forcedsplits_filename": "/etc/passwd"}, 422),
        ({"n_estimators": 1_000_000}, 422),
        ({"max_depth": 6, "min_child_samples": 10}, 201),
        ({"n_estimators": 300, "num_leaves": 64, "max_depth": 8}, 422),
        ({"n_estimators": 250, "num_leaves": 32, "max_depth": 5}, 201),
    ],
    ids=["machines", "threads", "file", "huge", "tuning", "combined", "at-the-limit"],
)
@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user_2@seita.nl"], indirect=True
)
def test_post_forecast_automation_accepts_only_bounded_model_params(
    app,
    db,
    add_battery_assets,
    requesting_user,
    model_params,
    status_code,
):
    """Model params of a forecast automation are limited to bounded tuning knobs."""
    battery = add_battery_assets["Test battery"]
    name = f"Forecasts with model params {sorted(model_params)}"
    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:post_automation", id=battery.id),
            json={
                "name": name,
                "cron": "0 6 * * *",
                "type": "forecasting",
                "parameters": {"sensor": battery.sensors[0].id},
                "config": {"model-params": model_params},
            },
        )
    assert response.status_code == status_code, response.json
    if status_code == 422:
        assert "model-params" in str(response.json)
        assert (
            db.session.execute(
                select(Automation).filter_by(name=name)
            ).scalar_one_or_none()
            is None
        )


@pytest.mark.parametrize(
    "requesting_user, is_admin",
    [("test_prosumer_user_2@seita.nl", False), ("test_admin_user@seita.nl", True)],
    indirect=["requesting_user"],
)
def test_activating_a_too_frequent_automation_is_refused(
    app, db, add_battery_assets, requesting_user, is_admin
):
    """An inactive automation that runs too often (e.g. a copy of one an admin set up) may not be activated by a non-admin."""
    battery = add_battery_assets["Test battery"]
    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:post_automation", id=battery.id),
            json={
                "name": f"Copied frequent forecasts ({requesting_user.email})",
                "cron": "0 6 * * *",
                "type": "forecasting",
                "parameters": {"sensor": battery.sensors[0].id},
                "active": False,
            },
        )
        assert response.status_code == 201, response.json
        automation_id = response.json["id"]
        automation = db.session.get(Automation, automation_id)
        automation.cronstr = "* * * * *"  # as copied from an automation an admin set up
        db.session.commit()
        url = url_for(
            "AssetAPI:patch_automation", id=battery.id, automation_id=automation_id
        )

        response = client.patch(url, json={"active": True})
        if is_admin:
            assert response.status_code == 200, response.json
            assert db.session.get(Automation, automation_id).active
            return
        assert response.status_code == 422, response.json
        assert "cron" in str(response.json["message"])
        assert not db.session.get(Automation, automation_id).active

        # Other changes to the inactive automation are still possible
        response = client.patch(url, json={"name": "Renamed copy"})
        assert response.status_code == 200, response.json

        # The interval is the one for the automation's type (an hour for forecasting)
        db.session.get(Automation, automation_id).cronstr = "*/15 * * * *"
        db.session.commit()
        response = client.patch(url, json={"active": True})
        assert response.status_code == 422, response.json
        assert "forecasting automations" in str(response.json["message"])
        assert not db.session.get(Automation, automation_id).active

        # Activating it with a cron expression that is allowed is fine
        response = client.patch(url, json={"active": True, "cron": "0 * * * *"})
        assert response.status_code == 200, response.json
        automation = db.session.get(Automation, automation_id)
        assert automation.active and automation.cronstr == "0 * * * *"


@pytest.mark.parametrize(
    "cron, allowed",
    [
        ("* * * * *", False),
        ("*/5 * * * *", False),
        ("0,10 * * * *", False),
        ("*/15 * * * *", False),  # forecasting automations may run once an hour
        ("0,30 * * * *", False),
        ("0 6-18 * * *", True),
        ("0 * * * *", True),
        ("0 6 * * *", True),
    ],
)
@pytest.mark.parametrize(
    "requesting_user, is_admin",
    [("test_prosumer_user_2@seita.nl", False), ("test_admin_user@seita.nl", True)],
    indirect=["requesting_user"],
)
def test_automation_cron_may_not_run_too_often(
    app,
    db,
    add_battery_assets,
    requesting_user,
    is_admin,
    cron,
    allowed,
):
    """Non-admins may not set up a forecasting automation that runs more often than once an hour,
    neither when creating it nor when changing its cron expression."""
    battery = add_battery_assets["Test battery"]
    name = f"Forecasts on cron {cron} by {requesting_user.email}"
    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:post_automation", id=battery.id),
            json={
                "name": name,
                "cron": cron,
                "type": "forecasting",
                "parameters": {"sensor": battery.sensors[0].id},
            },
        )
        if allowed or is_admin:
            assert response.status_code == 201, response.json
        else:
            assert response.status_code == 422, response.json
            assert "cron" in str(response.json["message"])
            assert (
                db.session.execute(
                    select(Automation).filter_by(name=name)
                ).scalar_one_or_none()
                is None
            )

        # Changing the cron expression of an existing automation is held to the same rule
        response = client.post(
            url_for("AssetAPI:post_automation", id=battery.id),
            json={
                "name": f"{name} (daily)",
                "cron": "0 6 * * *",
                "type": "forecasting",
                "parameters": {"sensor": battery.sensors[0].id},
            },
        )
        assert response.status_code == 201, response.json
        automation_id = response.json["id"]
        response = client.patch(
            url_for(
                "AssetAPI:patch_automation",
                id=battery.id,
                automation_id=automation_id,
            ),
            json={"cron": cron},
        )
        if allowed or is_admin:
            assert response.status_code == 200, response.json
        else:
            assert response.status_code == 422, response.json
            assert db.session.get(Automation, automation_id).cronstr == "0 6 * * *"


@pytest.mark.parametrize(
    "setting, cron, allowed",
    [
        # One interval for all types is still accepted
        (timedelta(minutes=5), "*/5 * * * *", True),
        (timedelta(minutes=5), "* * * * *", False),
        # A type that is not named gets the default
        ({"default": timedelta(minutes=10)}, "*/10 * * * *", True),
        ({"default": timedelta(minutes=10)}, "*/5 * * * *", False),
        ({"forecasting": timedelta(minutes=30)}, "*/30 * * * *", True),
        ({"forecasting": timedelta(minutes=30)}, "*/15 * * * *", False),
        ({"scheduling": timedelta(minutes=1)}, "*/5 * * * *", False),  # default 15 min
    ],
)
@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user_2@seita.nl"], indirect=True
)
def test_automation_min_interval_per_type(
    app, db, add_battery_assets, requesting_user, monkeypatch, setting, cron, allowed
):
    """The minimum interval is set per automation type, with a default for types not named."""
    monkeypatch.setitem(app.config, "FLEXMEASURES_AUTOMATION_MIN_INTERVAL", setting)
    battery = add_battery_assets["Test battery"]
    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:post_automation", id=battery.id),
            json={
                "name": f"Forecasts on cron {cron} ({len(str(setting))})",
                "cron": cron,
                "type": "forecasting",
                "parameters": {"sensor": battery.sensors[0].id},
            },
        )
    assert response.status_code == (201 if allowed else 422), response.json
    if not allowed:
        assert "forecasting automations may run at most once every" in str(
            response.json["message"]
        )


def test_automation_min_interval_defaults():
    from flexmeasures.data.services.automations import automation_min_interval
    from flexmeasures.utils.config_defaults import Config

    setting = Config.FLEXMEASURES_AUTOMATION_MIN_INTERVAL
    assert automation_min_interval("scheduling", setting) == timedelta(minutes=15)
    assert automation_min_interval("forecasting", setting) == timedelta(hours=1)
    assert automation_min_interval("reporting", setting) == timedelta(minutes=15)
    assert automation_min_interval("ingestion", setting) == timedelta(minutes=1)
    assert automation_min_interval("a-plugin-type", setting) == timedelta(minutes=15)


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


def _post_forecast_automation(client, battery, sensor_id: int, config: dict) -> dict:
    """Create a forecast automation through the API, returning the response body."""
    response = client.post(
        url_for("AssetAPI:post_automation", id=battery.id),
        json={
            "name": "Forecasts to edit",
            "cron": "0 6 * * *",
            "type": "forecasting",
            "parameters": {"sensor": sensor_id},
            "config": config,
        },
    )
    assert response.status_code == 201, response.json
    return response.json


def _patch_automation(client, battery, automation_id: int, payload: dict):
    return client.patch(
        url_for(
            "AssetAPI:patch_automation",
            id=battery.id,
            automation_id=automation_id,
        ),
        json=payload,
    )


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user_2@seita.nl"], indirect=True
)
def test_patch_automation_parameters_config_and_source(
    app,
    db,
    add_battery_assets,
    requesting_user,
):
    """An automation's parameters, config and data source can be changed after creation, each validated as on creation.

    A new config moves the automation onto the data source storing it, and leaves the old source as it was,
    and each change starts a new revision without touching the cursor.
    """
    from flexmeasures.data.models.audit_log import AssetAuditLog

    battery = add_battery_assets["Test battery"]
    first_sensor, second_sensor = battery.sensors[0], battery.sensors[1]
    with app.test_client() as client:
        created = _post_forecast_automation(
            client, battery, first_sensor.id, {"missing-threshold": 0.5}
        )
    automation = db.session.get(Automation, created["id"])
    first_source = automation.generator
    first_config = dict(first_source.attributes["data_generator"]["config"])
    cursor, revision = automation.cursor, automation.revision

    # New parameters keep the data source.
    with app.test_client() as client:
        response = _patch_automation(
            client, battery, automation.id, {"parameters": {"sensor": second_sensor.id}}
        )
    assert response.status_code == 200, response.json
    assert automation.parameters == {"sensor": second_sensor.id}
    assert automation.generator_id == first_source.id
    assert automation.revision == revision + 1
    assert automation.cursor == cursor
    assert automation.execution_user_id == requesting_user.id

    # A new config moves the automation onto another data source, and keeps its forecaster.
    with app.test_client() as client:
        response = _patch_automation(
            client, battery, automation.id, {"config": {"missing-threshold": 0.2}}
        )
    assert response.status_code == 200, response.json
    second_source = automation.generator
    assert second_source.id != first_source.id
    assert second_source.model == first_source.model
    assert (
        second_source.attributes["data_generator"]["config"]["missing-threshold"] == 0.2
    )
    assert first_source.attributes["data_generator"]["config"] == first_config
    assert automation.parameters == {"sensor": second_sensor.id}
    assert automation.revision == revision + 2
    assert automation.cursor == cursor
    audit_events = db.session.scalars(
        select(AssetAuditLog.event).filter_by(affected_asset_id=battery.id)
    ).all()
    assert any(
        f"data source: {first_source.id} → {second_source.id}" in event
        for event in audit_events
    )

    # Naming the earlier data source moves the automation back onto it.
    with app.test_client() as client:
        response = _patch_automation(
            client, battery, automation.id, {"source": first_source.id}
        )
    assert response.status_code == 200, response.json
    assert automation.generator_id == first_source.id

    # Sending what the automation already has changes nothing, so no new revision either.
    with app.test_client() as client:
        response = _patch_automation(
            client,
            battery,
            automation.id,
            {"parameters": {"sensor": second_sensor.id}, "source": first_source.id},
        )
    assert response.status_code == 200, response.json
    assert automation.revision == revision + 3


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user_2@seita.nl"], indirect=True
)
@pytest.mark.parametrize(
    "payload, field",
    [
        ({"source": "FIRST_SOURCE", "config": {}}, "source"),
        ({"parameters": {"sensor": "SENSOR", "start": "2026-01-01T00:00+01:00"}}, None),
        ({"parameters": {"sensor": -1}}, "parameters"),
        ({"config": {"missing-threshold": "lots"}}, "config"),
        ({"data-generator": "NoSuchForecaster"}, None),
    ],
)
def test_patch_automation_with_invalid_definition(
    app,
    db,
    add_battery_assets,
    requesting_user,
    payload,
    field,
):
    """An invalid edit is refused as an invalid creation is, and leaves the automation as it was."""
    battery = add_battery_assets["Test battery"]
    sensor = battery.sensors[0]
    with app.test_client() as client:
        created = _post_forecast_automation(client, battery, sensor.id, {})
    automation = db.session.get(Automation, created["id"])
    generator_id, revision = automation.generator_id, automation.revision
    payload = json.loads(
        json.dumps(payload)
        .replace('"FIRST_SOURCE"', str(generator_id))
        .replace('"SENSOR"', str(sensor.id))
    )
    with app.test_client() as client:
        response = _patch_automation(client, battery, automation.id, payload)
    assert response.status_code == 422, response.json
    if field is not None:
        assert field in json.dumps(response.json["message"])
    db.session.expire_all()
    automation = db.session.get(Automation, created["id"])
    assert automation.parameters == {"sensor": sensor.id}
    assert automation.generator_id == generator_id
    assert automation.revision == revision


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user_2@seita.nl"], indirect=True
)
def test_patch_automation_onto_inaccessible_sensor(
    app,
    db,
    add_battery_assets,
    setup_generic_assets,
    requesting_user,
):
    """New parameters are checked against the editing user's access to the sensors they name, as on creation."""
    battery = add_battery_assets["Test battery"]
    someone_elses_sensor = Sensor(
        name="wind power",
        generic_asset=setup_generic_assets[
            "test_wind_turbine"
        ],  # owned by the Supplier account
        event_resolution=timedelta(minutes=15),
        unit="MW",
    )
    db.session.add(someone_elses_sensor)
    db.session.commit()
    with app.test_client() as client:
        created = _post_forecast_automation(client, battery, battery.sensors[0].id, {})
        response = _patch_automation(
            client,
            battery,
            created["id"],
            {"parameters": {"sensor": someone_elses_sensor.id}},
        )
    assert response.status_code == 403, response.json
    # The edit adds the sensor, which the refusal says.
    assert response.json["message"] == (
        f"You cannot change this automation, because it would then read data from sensor {someone_elses_sensor.id},"
        " which you cannot read data from yourself."
    )
    db.session.expire_all()
    automation = db.session.get(Automation, created["id"])
    assert automation.parameters == {"sensor": battery.sensors[0].id}


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user_2@seita.nl"], indirect=True
)
def test_patch_schedule_automation_source(
    app,
    db,
    add_battery_assets,
    add_automations,
    requesting_user,
):
    """A schedule automation's data source follows from its asset, so an edit cannot name one."""
    battery = add_battery_assets["Test battery"]
    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:post_automation", id=battery.id),
            json={
                "name": "Schedules to edit",
                "cron": "0 12 * * *",
                "type": "scheduling",
                "parameters": {"duration": "PT12H"},
            },
        )
        assert response.status_code == 201, response.json
        response = _patch_automation(
            client,
            battery,
            response.json["id"],
            {"source": add_automations[0].generator_id},
        )
    assert response.status_code == 422, response.json
    assert "schedule automation cannot name a source" in json.dumps(
        response.json["message"]
    )


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user_2@seita.nl"], indirect=True
)
def test_patch_automation_keeps_the_run_user(
    app,
    db,
    add_battery_assets,
    setup_roles_users,
    requesting_user,
):
    """An edit leaves the user whom the automation runs as alone, where that user may use the sensors of the edited definition, too."""
    battery = add_battery_assets["Test battery"]
    creator_id = setup_roles_users["Test Prosumer User"]
    with app.test_client() as client:
        created = _post_forecast_automation(client, battery, battery.sensors[0].id, {})
    automation = db.session.get(Automation, created["id"])
    automation.execution_user_id = creator_id
    db.session.commit()

    for payload in (
        {"name": "Renamed forecasts"},
        {"parameters": {"sensor": battery.sensors[1].id}},
    ):
        with app.test_client() as client:
            response = _patch_automation(client, battery, automation.id, payload)
        assert response.status_code == 200, response.json
        assert automation.execution_user_id == creator_id
        assert response.json["runs-as"] == {
            "id": creator_id,
            "name": "Test Prosumer User",
        }


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user_2@seita.nl"], indirect=True
)
@pytest.mark.parametrize("run_user", ["Test Dummy User", None])
@pytest.mark.parametrize("edit_along", [True, False])
def test_patch_automation_refused_for_the_run_user_unless_taken_over(
    app,
    db,
    add_battery_assets,
    setup_roles_users,
    requesting_user,
    run_user,
    edit_along,
):
    """An edit which the user whom the automation runs as could not run is refused, naming both users,
    until the editor takes the runs over with run-as-me, which the asset's audit log records.

    The run user is either someone without access to the asset's sensors, or a user who no longer exists (None).
    Taking over works together with an edit, and on its own.
    """
    from flexmeasures.data.models.audit_log import AssetAuditLog

    battery = add_battery_assets["Test battery"]
    run_user_id = setup_roles_users[run_user] if run_user else 987654
    with app.test_client() as client:
        created = _post_forecast_automation(client, battery, battery.sensors[0].id, {})
    automation = db.session.get(Automation, created["id"])
    automation.execution_user_id = run_user_id
    db.session.commit()
    new_parameters = {"sensor": battery.sensors[1].id}

    with app.test_client() as client:
        response = _patch_automation(
            client, battery, automation.id, {"parameters": new_parameters}
        )
    assert response.status_code == 403, response.json
    message = response.json["message"]
    assert message.endswith(
        f" Send run-as-me to have it run as you, Test Prosumer User 2 (user {requesting_user.id}), instead."
    )
    # A client with its own way to take over recognises the refusal, and can say it without the API's hint.
    assert response.json["reason"] == "run-user-lacks-access"
    assert message.startswith(response.json["refusal"])
    assert "run-as-me" not in response.json["refusal"]
    if run_user:
        assert response.json["refusal"] == (
            f"You cannot change this automation, because it would then read data from sensor {battery.sensors[1].id},"
            f" which {run_user} (user {run_user_id}), whom it runs as, cannot read data from."
        )
    else:
        assert f"user {run_user_id}, who is missing or inactive" in message
    db.session.expire_all()
    automation = db.session.get(Automation, created["id"])
    assert automation.parameters == {"sensor": battery.sensors[0].id}
    assert automation.execution_user_id == run_user_id

    takeover = {"run-as-me": True}
    if edit_along:
        takeover["parameters"] = new_parameters
    with app.test_client() as client:
        response = _patch_automation(client, battery, automation.id, takeover)
    assert response.status_code == 200, response.json
    assert automation.execution_user_id == requesting_user.id
    audit_events = db.session.scalars(
        select(AssetAuditLog.event).filter_by(affected_asset_id=battery.id)
    ).all()
    previous_run_user = (
        f"{run_user} (user {run_user_id})" if run_user else f"user {run_user_id}"
    )
    assert any(
        f"runs as: {previous_run_user} → Test Prosumer User 2 (user {requesting_user.id})"
        in event
        for event in audit_events
    )

    # The editor now runs the automation, so their own access is all an edit needs.
    with app.test_client() as client:
        response = _patch_automation(
            client, battery, automation.id, {"parameters": new_parameters}
        )
    assert response.status_code == 200, response.json
    assert automation.parameters == new_parameters


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user_2@seita.nl"], indirect=True
)
def test_trigger_automation_refused_for_the_run_user(
    app,
    db,
    add_battery_assets,
    setup_roles_users,
    requesting_user,
):
    """A run on demand that the user the automation runs as may not run is refused with the edit's reason, so the UI can word the takeover its own way.

    The run records nothing of how to take over, as the API, the CLI and the edit form each say that in their own way.
    """
    battery = add_battery_assets["Test battery"]
    run_user_id = setup_roles_users["Test Dummy User"]
    with app.test_client() as client:
        created = _post_forecast_automation(client, battery, battery.sensors[0].id, {})
    automation = db.session.get(Automation, created["id"])
    automation.execution_user_id = run_user_id
    db.session.commit()

    with app.test_client() as client:
        response = client.post(
            url_for(
                "AssetAPI:trigger_automation",
                id=battery.id,
                automation_id=automation.id,
            )
        )
    assert response.status_code == 403, response.json
    assert response.json["reason"] == "run-user-lacks-access"
    refusal = response.json["refusal"]
    assert refusal.startswith(
        f"Automation {automation.id} runs as Test Dummy User (user {run_user_id}), who does not have"
    )
    assert "run-as-me" not in refusal and "Run as me" not in refusal
    assert response.json["message"] == (
        f"{refusal} Send run-as-me in a PATCH of this automation to have it run as you instead."
    )


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user_2@seita.nl"], indirect=True
)
def test_patch_automation_keeping_an_inaccessible_sensor(
    app,
    db,
    add_battery_assets,
    setup_generic_assets,
    setup_roles_users,
    requesting_user,
):
    """An edit is checked against every sensor its definition involves, including one it keeps, such as a regressor in the stored config.

    Editing only the parameters of an automation whose config names a sensor the editor cannot read is refused,
    leaving the automation running as its creator, and so is taking over its runs.
    """
    from flexmeasures.data.services.automations import create_automation

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
    db.session.flush()
    # Set up through the CLI, which is trusted, by someone who may read the regressor.
    automation, _ = create_automation(
        battery,
        name="Forecasts with someone else's regressor",
        cronstr="0 6 * * *",
        automation_type="forecasting",
        parameters={"sensor": battery.sensors[0].id},
        config={"past-regressors": [someone_elses_sensor.id]},
        origin="CLI",
    )
    creator_id = setup_roles_users["Test Prosumer User"]
    automation.execution_user_id = creator_id
    db.session.commit()
    generator_id = automation.generator_id

    with app.test_client() as client:
        response = _patch_automation(
            client,
            battery,
            automation.id,
            {"parameters": {"sensor": battery.sensors[1].id}},
        )
    assert response.status_code == 403, response.json
    # The sensor is in the stored config already, so the refusal does not say the edit adds it.
    assert response.json["message"] == (
        f"You cannot change this automation, because it reads data from sensor {someone_elses_sensor.id} (already in its definition),"
        " which you cannot read data from yourself."
    )
    db.session.expire_all()
    automation = db.session.get(Automation, automation.id)
    assert automation.parameters == {"sensor": battery.sensors[0].id}
    assert automation.generator_id == generator_id
    assert automation.execution_user_id == creator_id

    with app.test_client() as client:
        response = _patch_automation(
            client, battery, automation.id, {"run-as-me": True}
        )
    assert response.status_code == 403, response.json
    assert f"sensor {someone_elses_sensor.id}" in response.json["message"]
    db.session.expire_all()
    automation = db.session.get(Automation, automation.id)
    assert automation.execution_user_id == creator_id
