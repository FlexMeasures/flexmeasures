import pytest

from flexmeasures.api.common.schemas.sensors import (
    SensorField,
    EntityAddressValidationError,
)
from flexmeasures.utils.entity_address_utils import build_entity_address


@pytest.mark.parametrize(
    "entity_address, entity_type, fm_scheme, exp_deserialization_name",
    [
        (
            build_entity_address(dict(sensor_id=1), "sensor"),
            "sensor",
            "fm1",
            "height",
        ),
        (
            build_entity_address(
                dict(market_name="epex_da"), "market", fm_scheme="fm0"
            ),
            "market",
            "fm0",
            "epex_da",
        ),
        (
            build_entity_address(
                dict(owner_id=1, asset_id=4), "connection", fm_scheme="fm0"
            ),
            "connection",
            "fm0",
            "Test battery with no known prices",
        ),
        (
            build_entity_address(
                dict(
                    weather_sensor_type_name="temperature",
                    latitude=33.4843866,
                    longitude=126.0,
                ),
                "weather_sensor",
                fm_scheme="fm0",
            ),
            "weather_sensor",
            "fm0",
            "temperature_sensor",
        ),
    ],
)
def test_sensor_field_straightforward(
    add_sensors,
    setup_markets,
    add_battery_assets,
    add_weather_sensors,
    entity_address,
    entity_type,
    fm_scheme,
    exp_deserialization_name,
):
    """Testing straightforward cases"""
    sf = SensorField(entity_type, fm_scheme)
    deser = sf.deserialize(entity_address, None, None)
    assert deser.name == exp_deserialization_name
    if fm_scheme == "fm0" and entity_type in ("connection", "market", "weather_sensor"):
        # These entity types are deserialized to Sensors, which have no entity address under the fm0 scheme
        return
    assert sf.serialize(entity_type, {entity_type: deser}) == entity_address


@pytest.mark.parametrize(
    "entity_address, entity_type, fm_scheme, error_msg",
    [
        (
            "ea1.2021-01.io.flexmeasures:some.weird:identifier%that^is*not)used",
            "market",
            "fm0",
            "Could not parse",
        ),
        (
            "ea1.2021-01.io.flexmeasures:fm1.some.weird:identifier%that^is*not)used",
            "market",
            "fm1",
            "Could not parse",
        ),
        (
            build_entity_address(
                dict(market_name="non_existing_market"), "market", fm_scheme="fm0"
            ),
            "market",
            "fm0",
            "doesn't exist",
        ),
        (
            build_entity_address(dict(sensor_id=-1), "sensor", fm_scheme="fm1"),
            "market",
            "fm1",
            "Could not parse",
        ),
        ("ea1.2021-13.io.flexmeasures:fm1.9", "sensor", "fm1", "date specification"),
    ],
)
def test_sensor_field_invalid(entity_address, entity_type, fm_scheme, error_msg):
    sf = SensorField(entity_type, fm_scheme)
    with pytest.raises(EntityAddressValidationError) as ve:
        sf.deserialize(entity_address, None, None)
    assert error_msg in str(ve)
