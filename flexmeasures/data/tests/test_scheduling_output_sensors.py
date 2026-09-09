from __future__ import annotations

import pytest

from flexmeasures import Sensor
from flexmeasures.data.services.scheduling import (
    _set_flex_context_output_sensors_consumption_is_positive,
    _set_flex_model_output_sensors_consumption_is_positive,
)


@pytest.fixture
def output_sensors(db, add_battery_assets, request) -> tuple[Sensor, Sensor]:
    """Two power sensors to use as output sensors, without a sign convention of their own.

    Each test gets its own pair, since these tests share a database and set an attribute on them.
    """
    battery = add_battery_assets["Test battery"]
    sensors = []
    for name in (f"{request.node.name} A", f"{request.node.name} B"):
        sensor = Sensor(
            name=name,
            generic_asset=battery,
            unit="MW",
            event_resolution=battery.sensors[0].event_resolution,
        )
        db.session.add(sensor)
        sensors.append(sensor)
    db.session.flush()
    return sensors[0], sensors[1]


def test_flex_model_output_sensor_given_by_id(db, output_sensors):
    """A flex-model that reaches the setter undeserialized still gets its sign convention recorded.

    Skipping the reference instead would leave the sensor on the default production-positive convention,
    under which the scheduler's consumption-positive values are saved sign-flipped.
    """
    consumption_sensor, production_sensor = output_sensors
    _set_flex_model_output_sensors_consumption_is_positive(
        [
            {
                "consumption": {"sensor": consumption_sensor.id},
                "production": {"sensor": production_sensor.id},
            }
        ]
    )
    assert consumption_sensor.attributes["consumption_is_positive"] is True
    assert production_sensor.attributes["consumption_is_positive"] is False


def test_flex_model_output_sensor_nested_in_the_multi_sensor_form(db, output_sensors):
    """A device flex-model nested under its own key is visited, too."""
    consumption_sensor, _ = output_sensors
    _set_flex_model_output_sensors_consumption_is_positive(
        [
            {
                "sensor": consumption_sensor.id,
                "sensor-flex-model": {"consumption": {"sensor": consumption_sensor.id}},
            }
        ]
    )
    assert consumption_sensor.attributes["consumption_is_positive"] is True


def test_flex_context_aggregate_sensor_given_by_id(db, output_sensors):
    """An aggregate output sensor is resolved from the field key and reference the client posted."""
    consumption_sensor, production_sensor = output_sensors
    _set_flex_context_output_sensors_consumption_is_positive(
        {
            "aggregate-consumption": {"sensor": consumption_sensor.id},
            "aggregate-production": {"sensor": production_sensor.id},
        }
    )
    assert consumption_sensor.attributes["consumption_is_positive"] is True
    assert production_sensor.attributes["consumption_is_positive"] is False


def test_flex_context_in_its_multi_commodity_list_form(db, output_sensors):
    """A multi-commodity flex-context is a list before deserialization, and is visited as one."""
    consumption_sensor, _ = output_sensors
    _set_flex_context_output_sensors_consumption_is_positive(
        [
            {
                "commodity": "electricity",
                "aggregate-consumption": {"sensor": consumption_sensor.id},
            }
        ]
    )
    assert consumption_sensor.attributes["consumption_is_positive"] is True


def test_flex_context_commodities_before_deserialization(db, output_sensors):
    """Per-commodity contexts are keyed `commodities` before deserialization, and `commodity_contexts` after."""
    consumption_sensor, _ = output_sensors
    _set_flex_context_output_sensors_consumption_is_positive(
        {
            "commodities": [
                {
                    "commodity": "gas",
                    "aggregate-consumption": {"sensor": consumption_sensor.id},
                }
            ]
        }
    )
    assert consumption_sensor.attributes["consumption_is_positive"] is True


def test_unresolvable_output_sensor_reference_is_reported(db, add_battery_assets):
    """A reference that names no sensor is reported, rather than passing unnoticed."""
    with pytest.raises(ValueError, match="which does not exist"):
        _set_flex_model_output_sensors_consumption_is_positive(
            [{"consumption": {"sensor": 2147483647}}]
        )
    with pytest.raises(ValueError, match="could not be resolved"):
        _set_flex_model_output_sensors_consumption_is_positive(
            [{"consumption": {"sensor": ["not a sensor"]}}]
        )


def test_fields_that_are_not_sensor_references_are_left_alone(db, add_battery_assets):
    """A custom scheduler is free to use these field names for something else entirely."""
    _set_flex_model_output_sensors_consumption_is_positive(
        [{"consumption": "10 kW", "production": None}]
    )
    _set_flex_model_output_sensors_consumption_is_positive(None)
    _set_flex_context_output_sensors_consumption_is_positive(None)
