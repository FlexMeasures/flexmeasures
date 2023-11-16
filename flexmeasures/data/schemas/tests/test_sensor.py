import pytest
from flexmeasures.data.schemas.sensors import QuantityOrSensor
from marshmallow import ValidationError


@pytest.mark.parametrize(
    "sensor_id, src_quantity, dst_unit, fails",
    [
        # deserialize a sensor
        (1, None, "MWh", False),
        (1, None, "kWh", False),
        (1, None, "kW", False),
        (1, None, "EUR", True),
        (2, None, "EUR/kWh", False),
        (2, None, "EUR", True),
        # deserialize a quantity
        (None, "1MWh", "MWh", False),
        (None, "1 MWh", "kWh", False),
        (None, "1 MWh", "kW", True),
        (None, "100 EUR/MWh", "EUR/kWh", False),
        (None, "100 EUR/MWh", "EUR", True),
    ],
)
def test_quantity_or_sensor_deserialize(
    setup_dummy_sensors, sensor_id, src_quantity, dst_unit, fails
):

    schema = QuantityOrSensor(to_unit=dst_unit)

    try:
        if sensor_id is None:
            schema.deserialize(src_quantity)
        else:
            schema.deserialize({"sensor": sensor_id})
        assert not fails
    except ValidationError:
        assert fails


@pytest.mark.parametrize(
    "src_quantity, expected_magnitude",
    [
        ("1 kW", 0.001),
        ("10 kW", 0.01),
        ("100 kW", 0.1),
        ("1 MW", 1),
        ("1.2 GW", 1200),
        ("2000 kVA", 2),
        ("3600/4.184 cal/h", 1e-6),
    ],
)
def test_quantity_or_sensor_conversion(
    setup_dummy_sensors, src_quantity, expected_magnitude
):

    schema = QuantityOrSensor(to_unit="MW")
    assert schema.deserialize(src_quantity).magnitude == expected_magnitude
