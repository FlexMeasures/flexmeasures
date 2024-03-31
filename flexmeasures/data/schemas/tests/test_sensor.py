import pytest
from flexmeasures import Sensor
from flexmeasures.data.schemas.sensors import QuantityOrSensor
from flexmeasures.utils.unit_utils import ur
from marshmallow import ValidationError


@pytest.mark.parametrize(
    "sensor_id, src_quantity, dst_unit, fails, exp_dst_quantity",
    [
        # deserialize a sensor
        (1, None, "MWh", False, None),
        (1, None, "kWh", False, None),
        (1, None, "kW", False, None),
        (1, None, "EUR", True, None),
        (2, None, "EUR/kWh", False, None),
        (2, None, "EUR", True, None),
        # deserialize a quantity
        (None, "1MWh", "MWh", False, "1 MWh"),
        (None, "1 MWh", "kWh", False, "1000.0 kWh"),
        (None, "1 MWh", "kW", True, None),
        (None, "100 EUR/MWh", "EUR/kWh", False, "0.1 EUR/kWh"),
        (None, "100 EUR/MWh", "EUR", True, None),
        (None, "1 EUR/kWh", "/MWh", False, "1000.0 EUR/MWh"),
    ],
)
def test_quantity_or_sensor_deserialize(
    setup_dummy_sensors, sensor_id, src_quantity, dst_unit, fails, exp_dst_quantity
):

    schema = QuantityOrSensor(to_unit=dst_unit)

    try:
        if sensor_id is None:
            dst_quantity = schema.deserialize(src_quantity)
            if dst_quantity is not None:
                assert dst_quantity == ur.Quantity(exp_dst_quantity)
                assert str(dst_quantity) == exp_dst_quantity
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


@pytest.mark.parametrize(
    "sensor_id, input_param, dst_unit, fails",
    [
        # deserialize a sensor
        (1, "sensor:1", "MWh", False),
        (1, "sensor:1", "kWh", False),
        (1, "sensor:1", "kW", False),
        (1, "sensor:1", "EUR", True),
        (2, "sensor:2", "EUR/kWh", False),
        (2, "sensor:2", "EUR", True),
        # deserialize a quantity
        (None, "1MWh", "MWh", False),
        (None, "1 MWh", "kWh", False),
        (None, "1 MWh", "kW", True),
        (None, "100 EUR/MWh", "EUR/kWh", False),
        (None, "100 EUR/MWh", "EUR", True),
    ],
)
def test_quantity_or_sensor_field(
    setup_dummy_sensors, sensor_id, input_param, dst_unit, fails, db
):

    field = QuantityOrSensor(to_unit=dst_unit)

    try:
        if sensor_id is None:
            val = field.convert(input_param, None, None)
            assert val.units == ur.Unit(dst_unit)
        else:
            val = field.convert(input_param, None, None)
            assert val == db.session.get(Sensor, sensor_id)

        assert not fails
    except Exception:
        assert fails
