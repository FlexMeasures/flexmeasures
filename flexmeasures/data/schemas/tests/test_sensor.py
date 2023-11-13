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
        # deserialized a quantity
        (None, "1MWh", "MWh", False),
        (None, "1 MWh", "kWh", False),
        (None, "1 MWh", "kW", True),
        (None, "100 EUR/MWh", "EUR/kWh", False),
        (None, "100 EUR/MWh", "EUR", True),
    ],
)
def test_quantity_or_sensor(
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
