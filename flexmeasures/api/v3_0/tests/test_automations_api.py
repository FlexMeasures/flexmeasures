"""Tests for the automations endpoints (GET /api/v3_0/assets/<id>/automations[/<automation_id>])."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from flask import url_for
from sqlalchemy import select

from flexmeasures.data.models.automations import Automation
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.time_series import Sensor


@pytest.fixture(scope="function")
def add_automations(fresh_db, add_battery_assets_fresh_db):
    battery = add_battery_assets_fresh_db["Test battery"]
    generator = DataSource(
        name="automations API test generator",
        type="forecaster",
        model="TrainPredictPipeline",
    )
    automations = [
        Automation(
            asset_id=battery.id,
            generator=generator,
            type="forecasts",
            name="Day-ahead forecasts",
            cronstr="0 6 * * *",
            timezone="Europe/Amsterdam",
            scheduling_cursor=datetime(2026, 7, 11, 4, 0, tzinfo=timezone.utc),
            active=True,
            parameters={"sensor": battery.sensors[0].id},
        ),
        Automation(
            asset_id=battery.id,
            generator=generator,
            type="forecasts",
            name="Intraday forecasts",
            cronstr="0 * * * *",
            timezone="UTC",
            scheduling_cursor=datetime(2026, 7, 11, 5, 0, tzinfo=timezone.utc),
            active=False,
            parameters={"sensor": battery.sensors[0].id},
        ),
    ]
    fresh_db.session.add_all(automations)
    fresh_db.session.flush()
    return automations


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
    add_battery_assets_fresh_db,
    add_automations,
    requesting_user,
    expected_status_code,
):
    battery = add_battery_assets_fresh_db["Test battery"]
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
    add_battery_assets_fresh_db,
    add_automations,
    requesting_user,
):
    battery = add_battery_assets_fresh_db["Test battery"]
    with app.test_client() as client:
        response = client.get(
            url_for("AssetAPI:get_automations", id=battery.id),
        )
    assert response.status_code == 200
    automations = response.json["automations"]
    assert len(automations) == 2
    day_ahead = next(a for a in automations if a["name"] == "Day-ahead forecasts")
    assert day_ahead["type"] == "forecasts"
    assert day_ahead["cronstr"] == "0 6 * * *"
    assert day_ahead["timezone"] == "Europe/Amsterdam"
    assert day_ahead["scheduling_cursor"] == "2026-07-11T04:00:00+00:00"
    assert day_ahead["recurrence_description"] == "At 06:00"
    assert day_ahead["active"] is True
    assert day_ahead["created_at"] is not None
    # generator and parameters are not listed
    assert "generator_id" not in day_ahead
    assert "generator" not in day_ahead
    assert "parameters" not in day_ahead


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_get_automation_details(
    app,
    add_battery_assets_fresh_db,
    add_automations,
    requesting_user,
):
    battery = add_battery_assets_fresh_db["Test battery"]
    automation = add_automations[0]
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
    assert response.json["scheduling_cursor"] == "2026-07-11T04:00:00+00:00"
    assert response.json["parameters"] == {"sensor": battery.sensors[0].id}
    assert response.json["job_stats"] == {}  # this automation has not queued any jobs
    # the sensor to forecast is both read from (its history) and written to
    sensor = {"id": battery.sensors[0].id, "name": battery.sensors[0].name}
    assert response.json["input_sensors"] == [sensor]
    assert response.json["output_sensors"] == [sensor]


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_get_automation_of_other_asset(
    app,
    add_battery_assets_fresh_db,
    add_automations,
    requesting_user,
):
    """Requesting an automation via an asset it does not belong to should return 404."""
    other_asset = add_battery_assets_fresh_db["Test small battery"]
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
    add_battery_assets_fresh_db,
    add_automations,
    requesting_user,
):
    battery = add_battery_assets_fresh_db["Test battery"]
    with app.test_client() as client:
        response = client.get(
            url_for("AssetAPI:get_automation", id=battery.id, automation_id=9999),
        )
    assert response.status_code == 404


@pytest.mark.parametrize(
    "requesting_user, expected_status_code",
    [
        ("test_prosumer_user@seita.nl", 403),  # plain account member
        ("test_prosumer_user_2@seita.nl", 201),  # account admin
        ("test_dummy_user_3@seita.nl", 403),  # different account
    ],
    indirect=["requesting_user"],
)
def test_post_automation(
    app,
    fresh_db,
    add_battery_assets_fresh_db,
    requesting_user,
    expected_status_code,
):
    """Only account admins (and consultants) can create automations; parameters are validated by type."""
    battery = add_battery_assets_fresh_db["Test battery"]
    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:post_automation", id=battery.id),
            json={
                "name": "Posted schedules",
                "cronstr": "0 0 * * *",
                "type": "schedules",
                "parameters": {"duration": "PT12H"},
            },
        )
    assert response.status_code == expected_status_code
    if expected_status_code == 201:
        assert response.json["name"] == "Posted schedules"
        assert response.json["active"] is True
        assert response.json["recurrence_description"] == "At 00:00"
        automation = fresh_db.session.get(Automation, response.json["id"])
        assert automation.parameters == {"duration": "PT12H"}
        # clean up for other tests in this module
        fresh_db.session.delete(automation)
        fresh_db.session.flush()


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user_2@seita.nl"], indirect=True
)
def test_post_automation_with_invalid_parameters(
    app,
    add_battery_assets_fresh_db,
    requesting_user,
):
    battery = add_battery_assets_fresh_db["Test battery"]
    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:post_automation", id=battery.id),
            json={
                "name": "Bad forecasts",
                "cronstr": "0 6 * * *",
                "type": "forecasts",
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
    fresh_db,
    add_battery_assets_fresh_db,
    requesting_user,
):
    """An automation's timezone can be set on creation and changed afterwards, as it can from the CLI."""
    battery = add_battery_assets_fresh_db["Test battery"]
    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:post_automation", id=battery.id),
            json={
                "name": "Seoul forecasts",
                "cronstr": "0 6 * * *",
                "timezone": "Asia/Seoul",
                "type": "forecasts",
                "parameters": {"sensor": battery.sensors[0].id},
            },
        )
    assert response.status_code == 201, response.json
    assert response.json["timezone"] == "Asia/Seoul"
    automation = fresh_db.session.execute(
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
    fresh_db,
    add_battery_assets_fresh_db,
    setup_generic_assets_fresh_db,
    requesting_user,
):
    """A regressor that filters on sources is a sensor reference, and still counts as a sensor read."""
    battery = add_battery_assets_fresh_db["Test battery"]
    someone_elses_sensor = Sensor(
        name="wind speed for a filtered regressor",
        generic_asset=setup_generic_assets_fresh_db[
            "test_wind_turbine"
        ],  # owned by the Supplier account
        event_resolution=timedelta(minutes=15),
        unit="m/s",
    )
    fresh_db.session.add(someone_elses_sensor)
    fresh_db.session.flush()
    data_sources_before = set(fresh_db.session.scalars(select(DataSource.id)).all())

    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:post_automation", id=battery.id),
            json={
                "name": "Forecasts regressing on another account's sensor",
                "cronstr": "0 6 * * *",
                "type": "forecasts",
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
        fresh_db.session.execute(
            select(Automation).filter_by(
                name="Forecasts regressing on another account's sensor"
            )
        ).scalar_one_or_none()
        is None
    )
    # a refused request also leaves behind no data source for the forecaster it would have run
    assert (
        set(fresh_db.session.scalars(select(DataSource.id)).all())
        == data_sources_before
    )


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user_2@seita.nl"], indirect=True
)
def test_post_automation_with_inaccessible_sensor(
    app,
    fresh_db,
    add_battery_assets_fresh_db,
    setup_generic_assets_fresh_db,
    requesting_user,
):
    """An account admin cannot set up an automation on a sensor of another account."""
    battery = add_battery_assets_fresh_db["Test battery"]
    someone_elses_sensor = Sensor(
        name="wind speed",
        generic_asset=setup_generic_assets_fresh_db[
            "test_wind_turbine"
        ],  # owned by the Supplier account
        event_resolution=timedelta(minutes=15),
        unit="m/s",
    )
    fresh_db.session.add(someone_elses_sensor)
    fresh_db.session.flush()

    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:post_automation", id=battery.id),
            json={
                "name": "Forecasts of another account's sensor",
                "cronstr": "0 6 * * *",
                "type": "forecasts",
                "parameters": {"sensor": someone_elses_sensor.id},
            },
        )
    assert response.status_code == 403
    assert str(someone_elses_sensor.id) in response.json["message"]
    assert someone_elses_sensor.name not in response.json["message"]
    assert (
        fresh_db.session.execute(
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
                "cronstr": "0 6 * * *",
                "type": "forecasts",
                "parameters": {"sensor": own_sensor.id},
            },
        )
    assert response.status_code == 201, response.json
    # clean up for other tests in this module
    fresh_db.session.delete(fresh_db.session.get(Automation, response.json["id"]))
    fresh_db.session.flush()


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user_2@seita.nl"], indirect=True
)
def test_post_schedule_automation_with_inaccessible_output_sensor(
    app,
    fresh_db,
    add_battery_assets_fresh_db,
    setup_generic_assets_fresh_db,
    requesting_user,
):
    """Sensors that a schedule would be recorded on are checked, wherever they are named.

    The aggregate power schedule is recorded on the flex-context's aggregate-consumption
    sensor, so that one needs to be writable, too — not just the flex-model's own sensors.
    """
    battery = add_battery_assets_fresh_db["Test battery"]
    someone_elses_sensor = Sensor(
        name="aggregate consumption",
        generic_asset=setup_generic_assets_fresh_db[
            "test_wind_turbine"
        ],  # owned by the Supplier account
        event_resolution=timedelta(minutes=15),
        unit="MW",
    )
    fresh_db.session.add(someone_elses_sensor)
    fresh_db.session.flush()

    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:post_automation", id=battery.id),
            json={
                "name": "Schedules aggregated onto another account's sensor",
                "cronstr": "0 0 * * *",
                "type": "schedules",
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
        ("test_prosumer_user@seita.nl", 403),  # plain account member
        ("test_prosumer_user_2@seita.nl", 200),  # account admin
    ],
    indirect=["requesting_user"],
)
def test_patch_automation(
    app,
    fresh_db,
    add_battery_assets_fresh_db,
    add_automations,
    requesting_user,
    expected_status_code,
):
    battery = add_battery_assets_fresh_db["Test battery"]
    automation = add_automations[0]
    original_name = automation.name
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
        # restore for other tests in this module
        automation.name = original_name
        automation.active = True
        fresh_db.session.flush()


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user_2@seita.nl"], indirect=True
)
def test_delete_automation(
    app,
    fresh_db,
    add_battery_assets_fresh_db,
    add_automations,
    requesting_user,
):
    battery = add_battery_assets_fresh_db["Test battery"]
    automation = Automation(
        asset_id=battery.id,
        # a forecast automation is required to have a data generator holding its forecaster config
        generator=add_automations[0].generator,
        type="forecasts",
        name="To be deleted",
        cronstr="0 6 * * *",
        parameters={"sensor": battery.sensors[0].id},
    )
    fresh_db.session.add(automation)
    fresh_db.session.flush()
    with app.test_client() as client:
        response = client.delete(
            url_for(
                "AssetAPI:delete_automation",
                id=battery.id,
                automation_id=automation.id,
            ),
        )
        assert response.status_code == 204
        assert fresh_db.session.get(Automation, automation.id) is None

        # deleting again yields the documented 404
        response = client.delete(
            url_for(
                "AssetAPI:delete_automation",
                id=battery.id,
                automation_id=automation.id,
            ),
        )
        assert response.status_code == 404
