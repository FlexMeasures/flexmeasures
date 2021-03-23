import pytest

from flexmeasures.api.common.schemas.sensors import (
    SensorField,
    EntityAddressValidationError,
)
from flexmeasures.utils.entity_address_utils import build_entity_address


@pytest.mark.parametrize(
    "entity_address, entity_type, exp_deserialization_name",
    [
        (
            build_entity_address(dict(sensor_id=9), "sensor"),
            "sensor",
            "my daughter's height",
        ),
        (
            build_entity_address(dict(market_name="epex_da"), "market"),
            "market",
            "epex_da",
        ),
        (
            build_entity_address(dict(owner_id=1, asset_id=3), "connection"),
            "connection",
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
            ),
            "weather_sensor",
            "temperature_sensor",
        ),
    ],
)
def test_sensor_field_straightforward(
    entity_address, entity_type, exp_deserialization_name
):
    """Testing straightforward cases"""
    sf = SensorField(entity_type)
    deser = sf.deserialize(entity_address, None, None)
    assert deser.name == exp_deserialization_name
    assert sf.serialize(entity_type, {entity_type: deser}) == entity_address


@pytest.mark.parametrize(
    "entity_address, entity_type, error_msg",
    [
        (
            "ea1.2021-01.io.flexmeasures:some.weird:identifier%that^is*not)used",
            "market",
            "Could not parse",
        ),
        (
            build_entity_address(dict(market_name="non_existing_market"), "market"),
            "market",
            "doesn't exist",
        ),
        ("ea1.2021-13.io.flexmeasures:9", "sensor", "date specification"),
    ],
)
def test_sensor_field_invalid(entity_address, entity_type, error_msg):
    sf = SensorField(entity_type)
    with pytest.raises(EntityAddressValidationError) as ve:
        sf.deserialize(entity_address, None, None)
    assert error_msg in str(ve)
