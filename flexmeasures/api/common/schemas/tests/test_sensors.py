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
    ],
)
def test_sensor_field_straightforward(
    add_sensors,
    setup_markets,
    add_battery_assets,
    entity_address,
    entity_type,
    fm_scheme,
    exp_deserialization_name,
):
    """Testing straightforward cases"""
    sf = SensorField(entity_type, fm_scheme)
    deser = sf.deserialize(entity_address, None, None)
    assert deser.name == exp_deserialization_name
    assert sf.serialize(entity_type, {entity_type: deser}) == entity_address


@pytest.mark.parametrize(
    "entity_address, entity_type, fm_scheme, error_msg",
    [
        (
            build_entity_address(
                dict(market_name="epex_da"), "market", fm_scheme="fm0"
            ),
            "market",
            "fm0",
            "fm0 scheme is no longer supported",
        ),
        (
            "ea1.2021-01.io.flexmeasures:fm1.some.weird:identifier%that^is*not)used",
            "sensor",
            "fm1",
            "Could not parse",
        ),
        (
            build_entity_address(
                dict(sensor_id=99999999999999), "sensor", fm_scheme="fm1"
            ),
            "sensor",
            "fm1",
            "doesn't exist",
        ),
        (
            build_entity_address(dict(sensor_id=-1), "sensor", fm_scheme="fm1"),
            "sensor",
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
