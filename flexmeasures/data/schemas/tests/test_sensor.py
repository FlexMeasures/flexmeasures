import pytest
from flexmeasures import Sensor
from flexmeasures.data.schemas.sensors import (
    QuantityOrSensor,
    SensorReference,
    VariableQuantityField,
)
from flexmeasures.utils.unit_utils import ur
from marshmallow import ValidationError


@pytest.mark.parametrize(
    "src_quantity, dst_unit, fails, exp_dst_quantity",
    [
        # deserialize a sensor
        ({"sensor": 1}, "MWh", False, None),
        ({"sensor": 1}, "kWh", False, None),
        ({"sensor": 1}, "kW", False, None),
        ({"sensor": 1}, "EUR", True, None),
        ({"sensor": 1}, "/h", False, None),  # convertable to MWh²/h
        ({"sensor": 2}, "EUR/kWh", False, None),
        ({"sensor": 2}, "EUR", True, None),
        # deserialize a quantity
        (1, "%", False, "100.0 %"),
        (5, "%", False, "500.0 %"),
        ("1MWh", "MWh", False, "1 MWh"),
        ("1 MWh", "kWh", False, "1000.0 kWh"),
        ("1 MWh", "kW", True, None),
        ("100 EUR/MWh", "EUR/kWh", False, "0.1 EUR/kWh"),
        ("100 EUR/MWh", "EUR", True, None),
        ("1 EUR/kWh", "/MWh", False, "1.0 kEUR/MWh"),
        ("50%", "/MWh", False, "500.0 kWh/MWh"),
        ("/", "/MWh", True, None),
        ("/", "MWh", True, None),
        ("10 batteries", "MWh", True, None),
        # deserialize a time series specification
        (
            [{"start": "2024-08-17T11:00+02", "duration": "PT1H", "value": "2 MWh"}],
            "kWh",
            False,
            "2000.0 kWh",
        ),
        (
            [
                {
                    "start": "2024-08-17T11:00+02",
                    "duration": "PT1H",
                    "value": "829.4 Wh/kWh",
                }
            ],
            "/MWh",
            False,
            "829.4 kWh/MWh",
        ),
        (
            [
                {
                    "start": "2024-08-17T11:00+02",
                    "duration": "PT1H",
                    "value": "914.7 EUR/kWh",
                }
            ],
            "/MWh",
            False,
            "914.7 kEUR/MWh",
        ),
        # todo: uncomment after to_preferred gets rid of mEUR
        # (
        #     [{"start": "2024-08-17T11:00+02", "duration": "PT1H", "value": "120.8 EUR/MWh"}],
        #     "/kWh",
        #     False,
        #     "0.1208 EUR/kWh",
        # ),
    ],
)
def test_quantity_or_sensor_deserialize(
    setup_dummy_sensors, src_quantity, dst_unit, fails, exp_dst_quantity
):

    schema = VariableQuantityField(to_unit=dst_unit, return_magnitude=False)

    try:
        dst_quantity = schema.deserialize(src_quantity)
        if isinstance(src_quantity, (ur.Quantity, int, float)):
            assert dst_quantity == ur.Quantity(exp_dst_quantity)
            assert str(dst_quantity) == exp_dst_quantity
        elif isinstance(src_quantity, list):
            assert dst_quantity[0]["value"] == ur.Quantity(exp_dst_quantity)
            assert str(dst_quantity[0]["value"]) == exp_dst_quantity
        assert not fails
    except ValidationError as e:
        assert fails, e


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
    except Exception as e:
        assert fails, e


@pytest.mark.parametrize(
    "input_param, dst_unit, fails",
    [
        # deserialize a quantity
        ([{"value": 1, "datetime": "2024-07-21T00:15+07"}], "MWh", False),
        ([{"value": "1", "datetime": "2024-07-21T00:15+07"}], "MWh", True),
        ([{"value": "1MWh", "datetime": "2024-07-21T00:15+07"}], "MWh", False),
        ([{"value": "1000 kWh", "datetime": "2024-07-21T00:15+07"}], "MWh", False),
        ([{"value": "1 MW", "datetime": "2024-07-21T00:15+07"}], "MWh", True),
    ],
)
def test_time_series_field(input_param, dst_unit, fails, db):

    field = VariableQuantityField(
        to_unit=dst_unit,
        default_src_unit="MWh",
        return_magnitude=False,
    )

    try:
        val = field.convert(input_param, None, None)
        assert val[0]["value"].units == ur.Unit(dst_unit)
        assert val[0]["value"].magnitude == 1

        assert not fails
    except Exception as e:
        assert fails, e


def test_sensor_reference_backward_compatible(setup_dummy_sensors):
    """Plain ``{"sensor": <id>}`` deserializes to a :class:`Sensor`, not a :class:`SensorReference`.

    This verifies backward compatibility: existing flex-model/flex-context payloads that carry
    only a sensor ID must continue to produce a plain Sensor object so that no calling code
    needs to change.
    """
    sensor1, _, _, _ = setup_dummy_sensors
    field = VariableQuantityField(to_unit="MWh", return_magnitude=False)

    result = field.deserialize({"sensor": sensor1.id})

    assert isinstance(result, Sensor)
    assert result.id == sensor1.id


def test_sensor_reference_with_source_types(setup_dummy_sensors):
    """``{"sensor": <id>, "source-types": [...]}`` deserializes to a :class:`SensorReference`.

    The deserialized object exposes the same ``unit``, ``id``, and ``event_resolution``
    properties as the underlying sensor, and carries the requested ``source_types`` filter.
    """
    sensor1, _, _, _ = setup_dummy_sensors
    field = VariableQuantityField(to_unit="MWh", return_magnitude=False)

    result = field.deserialize(
        {"sensor": sensor1.id, "source-types": ["scheduler", "forecaster"]}
    )

    assert isinstance(result, SensorReference)
    assert result.sensor == sensor1
    assert result.id == sensor1.id
    assert result.unit == sensor1.unit
    assert result.event_resolution == sensor1.event_resolution
    assert result.source_types == ["scheduler", "forecaster"]
    assert result.exclude_source_types is None
    assert result.sources is None


def test_sensor_reference_with_exclude_source_types(setup_dummy_sensors):
    """``{"sensor": <id>, "exclude-source-types": [...]}`` deserializes to a :class:`SensorReference`.

    The ``exclude_source_types`` attribute is populated and ``source_types`` remains ``None``.
    """
    sensor1, _, _, _ = setup_dummy_sensors
    field = VariableQuantityField(to_unit="MWh", return_magnitude=False)

    result = field.deserialize(
        {"sensor": sensor1.id, "exclude-source-types": ["forecaster"]}
    )

    assert isinstance(result, SensorReference)
    assert result.sensor == sensor1
    assert result.source_types is None
    assert result.exclude_source_types == ["forecaster"]
    assert result.sources is None


def test_sensor_reference_with_sources(setup_dummy_sensors, setup_sources, db):
    """``{"sensor": <id>, "sources": [<source_id>]}`` deserializes to a :class:`SensorReference`.

    Each integer source ID in the list is resolved to a :class:`DataSource` instance via
    :class:`~flexmeasures.data.schemas.sources.DataSourceIdField`.
    """
    sensor1, _, _, _ = setup_dummy_sensors
    seita_source = setup_sources["Seita"]
    # Flush so that DataSources created by setup_sources get their DB-assigned primary keys.
    # create_sources() adds objects to the session without committing; without an explicit flush
    # the id column stays None whenever sensor1.id is already cached and no auto-flush fires.
    db.session.flush()
    field = VariableQuantityField(to_unit="MWh", return_magnitude=False)

    result = field.deserialize({"sensor": sensor1.id, "sources": [seita_source.id]})

    assert isinstance(result, SensorReference)
    assert result.sensor == sensor1
    assert result.source_types is None
    assert result.exclude_source_types is None
    assert result.sources is not None
    assert len(result.sources) == 1
    assert result.sources[0].id == seita_source.id


@pytest.mark.parametrize(
    "invalid_payload, expected_fragment",
    [
        (
            {"sensor": 1, "source-types": "scheduler"},
            "list of strings",
        ),
        (
            {"sensor": 1, "source-types": [1, 2]},
            "list of strings",
        ),
        (
            {"sensor": 1, "exclude-source-types": "forecaster"},
            "list of strings",
        ),
        (
            {"sensor": 1, "sources": 42},
            "list of data source IDs",
        ),
    ],
)
def test_sensor_reference_invalid_source_filter(
    setup_dummy_sensors, invalid_payload, expected_fragment
):
    """Malformed source filter values raise a :class:`~marshmallow.ValidationError`.

    The error message must contain the relevant fragment so callers get actionable feedback.
    """
    sensor1, _, _, _ = setup_dummy_sensors
    # Replace the placeholder sensor ID 1 with the real fixture ID so the sensor lookup
    # succeeds and the validation error comes from the source-filter branch, not the sensor lookup.
    payload = dict(invalid_payload)
    payload["sensor"] = sensor1.id

    field = VariableQuantityField(to_unit="MWh", return_magnitude=False)

    with pytest.raises(ValidationError) as exc_info:
        field.deserialize(payload)

    assert expected_fragment in str(exc_info.value)
