"""Triggering a schedule needs more than read access on the sensors the schedule will be recorded on.

Public sensors are readable by everyone, but only admins may record data on them,
so naming one as an output in a trigger must not let a member write a schedule into it.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from flask import url_for

from flexmeasures.api.v3_0.tests.utils import message_for_trigger_schedule
from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.models.time_series import Sensor


@pytest.fixture(scope="module")
def output_sensors(db, add_battery_assets):
    """Power and stock sensors on a public asset, and a power sensor next to the Prosumer's battery."""
    public_asset = GenericAsset(
        name="public site for outputs",
        generic_asset_type=db.session.query(GenericAssetType).first(),
    )
    own_asset = add_battery_assets["Test battery"]
    sensors = {
        "public power": Sensor(
            name="public power",
            unit="kW",
            event_resolution=timedelta(minutes=15),
            generic_asset=public_asset,
        ),
        "public stock": Sensor(
            name="public stock",
            unit="MWh",
            event_resolution=timedelta(0),
            generic_asset=public_asset,
        ),
        "own power": Sensor(
            name="own aggregate power",
            unit="kW",
            event_resolution=timedelta(minutes=15),
            generic_asset=own_asset,
        ),
    }
    db.session.add_all([public_asset, *sensors.values()])
    db.session.commit()
    return {name: sensor.id for name, sensor in sensors.items()}


OUTPUT_CASES = [
    ("flex-context", "aggregate-power", "public power", 403),
    ("flex-context", "aggregate-consumption", "public power", 403),
    ("flex-model", "consumption", "public power", 403),
    ("flex-model", "state-of-charge", "public stock", 403),
    ("flex-context", "aggregate-power", "own power", 202),
]


@pytest.mark.parametrize("flex_config, field, sensor_name, expected", OUTPUT_CASES)
@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_sensor_schedule_trigger_needs_write_access_to_outputs(
    app,
    add_market_prices,
    add_battery_assets,
    output_sensors,
    keep_scheduling_queue_empty,
    requesting_user,
    flex_config,
    field,
    sensor_name,
    expected,
):
    sensor = add_battery_assets["Test battery"].sensors[0]
    message = message_for_trigger_schedule()
    message.setdefault(flex_config, {})[field] = {"sensor": output_sensors[sensor_name]}

    with app.test_client() as client:
        response = client.post(
            url_for("SensorAPI:trigger_schedule", id=sensor.id), json=message
        )

    assert response.status_code == expected, response.json
    if expected == 403:
        assert "cannot record data on" in response.json["message"]
        assert field in response.json["message"]


@pytest.mark.parametrize("flex_config, field, sensor_name, expected", OUTPUT_CASES)
@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user@seita.nl"], indirect=True
)
def test_asset_schedule_trigger_needs_write_access_to_outputs(
    app,
    add_market_prices,
    add_battery_assets,
    output_sensors,
    keep_scheduling_queue_empty,
    requesting_user,
    flex_config,
    field,
    sensor_name,
    expected,
):
    battery = add_battery_assets["Test battery"]
    message = message_for_trigger_schedule()
    device_model = {**message["flex-model"], "sensor": battery.sensors[0].id}
    message["flex-model"] = [device_model]
    if flex_config == "flex-model":
        device_model[field] = {"sensor": output_sensors[sensor_name]}
    else:
        message.setdefault("flex-context", {})[field] = {
            "sensor": output_sensors[sensor_name]
        }

    with app.test_client() as client:
        response = client.post(
            url_for("AssetAPI:trigger_schedule", id=battery.id), json=message
        )

    assert response.status_code == expected, response.json
    if expected == 403:
        assert "cannot record data on" in response.json["message"]
