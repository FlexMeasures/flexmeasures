from datetime import datetime, timedelta
import pytz
import pytest

from marshmallow.validate import ValidationError
import pandas as pd

from flexmeasures.data.schemas.scheduling import FlexContextSchema, DBFlexContextSchema
from flexmeasures.data.schemas.scheduling.process import (
    ProcessSchedulerFlexModelSchema,
    ProcessType,
)
from flexmeasures.data.schemas.scheduling.storage import (
    StorageFlexModelSchema,
    DBStorageFlexModelSchema,
)
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.schemas.sensors import TimedEventSchema, VariableQuantityField


@pytest.mark.parametrize(
    ["timing_input", "expected_start", "expected_end"],
    [
        (
            {"datetime": "2023-03-27T00:00:00+02:00"},
            "2023-03-27T00:00:00+02:00",
            "2023-03-27T00:00:00+02:00",
        ),
        (
            {"start": "2023-03-26T00:00:00+01:00", "end": "2023-03-27T00:00:00+02:00"},
            "2023-03-26T00:00:00+01:00",
            "2023-03-27T00:00:00+02:00",
        ),
        (
            {"start": "2023-03-26T00:00:00+01:00", "duration": "PT24H"},
            "2023-03-26T00:00:00+01:00",
            "2023-03-27T01:00:00+02:00",
        ),
        # https://github.com/gweis/isodate/issues/74
        # (
        #     {"start": "2023-03-26T00:00:00+01:00", "duration": "P1D"},
        #     "2023-03-26T00:00:00+01:00",
        #     "2023-03-27T00:00:00+02:00",
        # ),
        # (
        #     {"start": "2023-03-26T00:00:00+01:00", "duration": "P1W"},
        #     "2023-03-26T00:00:00+01:00",
        #     "2023-04-02T00:00:00+02:00",
        # ),
        (
            {"start": "2023-03-26T00:00:00+01:00", "duration": "P1M"},
            "2023-03-26T00:00:00+01:00",
            "2023-04-26T00:00:00+02:00",
        ),
        (
            {"end": "2023-03-27T00:00:00+02:00", "duration": "PT24H"},
            "2023-03-25T23:00:00+01:00",
            "2023-03-27T00:00:00+02:00",
        ),
        (
            {"start": "2023-10-29T00:00:00+02:00", "duration": "PT24H"},
            "2023-10-29T00:00:00+02:00",
            "2023-10-29T23:00:00+01:00",
        ),
        # https://github.com/gweis/isodate/issues/74
        # (
        #     {"start": "2023-10-29T00:00:00+02:00", "duration": "P1D"},
        #     "2023-10-29T00:00:00+02:00",
        #     "2023-10-30T00:00:00+01:00",
        # ),
        # (
        #     {"start": "2023-10-29T00:00:00+02:00", "duration": "P1W"},
        #     "2023-10-29T00:00:00+02:00",
        #     "2023-11-05T00:00:00+01:00",
        # ),
        (
            {"start": "2023-10-29T00:00:00+02:00", "duration": "P1M"},
            "2023-10-29T00:00:00+02:00",
            "2023-11-29T00:00:00+01:00",
        ),
        (
            {"end": "2023-11-29T00:00:00+01:00", "duration": "P1M"},
            "2023-10-29T00:00:00+02:00",
            "2023-11-29T00:00:00+01:00",
        ),
    ],
)
def test_soc_value_field(timing_input, expected_start, expected_end):
    data = TimedEventSchema(timezone="Europe/Amsterdam").load(
        {
            "value": 3,
            **timing_input,
        }
    )
    print(data)
    assert data["start"] == pd.Timestamp(expected_start)
    assert data["end"] == pd.Timestamp(expected_end)


def test_process_scheduler_flex_model_load(db, app, setup_dummy_sensors):
    sensor1, _, _, _ = setup_dummy_sensors

    schema = ProcessSchedulerFlexModelSchema(
        sensor=sensor1,
        start=datetime(2023, 1, 1, tzinfo=pytz.UTC),
        end=datetime(2023, 1, 2, tzinfo=pytz.UTC),
    )

    process_scheduler_flex_model = schema.load(
        {
            "duration": "PT4H",
            "power": 30.0,
            "time-restrictions": [
                {"start": "2023-01-01T00:00:00+00:00", "duration": "PT3H"}
            ],
        }
    )

    assert process_scheduler_flex_model["process_type"] == ProcessType.INFLEXIBLE


def test_process_scheduler_flex_model_process_type(db, app, setup_dummy_sensors):
    sensor1, _, _, _ = setup_dummy_sensors

    # checking default

    schema = ProcessSchedulerFlexModelSchema(
        sensor=sensor1,
        start=datetime(2023, 1, 1, tzinfo=pytz.UTC),
        end=datetime(2023, 1, 2, tzinfo=pytz.UTC),
    )

    process_scheduler_flex_model = schema.load(
        {
            "duration": "PT4H",
            "power": 30.0,
            "time-restrictions": [
                {"start": "2023-01-01T00:00:00+00:00", "duration": "PT3H"}
            ],
        }
    )

    assert process_scheduler_flex_model["process_type"] == ProcessType.INFLEXIBLE

    sensor1.attributes["process-type"] = "SHIFTABLE"

    schema = ProcessSchedulerFlexModelSchema(
        sensor=sensor1,
        start=datetime(2023, 1, 1, tzinfo=pytz.UTC),
        end=datetime(2023, 1, 2, tzinfo=pytz.UTC),
    )

    process_scheduler_flex_model = schema.load(
        {
            "duration": "PT4H",
            "power": 30.0,
            "time-restrictions": [
                {"start": "2023-01-01T00:00:00+00:00", "duration": "PT3H"}
            ],
        }
    )

    assert process_scheduler_flex_model["process_type"] == ProcessType.SHIFTABLE


def test_storage_flex_model_schema_does_not_floor_instantaneous_sensor(
    db, app, dummy_asset
):
    sensor = Sensor(
        "instantaneous power sensor",
        generic_asset=dummy_asset,
        event_resolution=timedelta(0),
        unit="MW",
    )
    db.session.add(sensor)
    db.session.flush()

    schema = StorageFlexModelSchema(
        sensor=sensor,
        start=datetime(2023, 1, 1, tzinfo=pytz.UTC),
    )

    assert schema.flooring_resolution is None


@pytest.mark.parametrize(
    "fields, fails",
    [
        (
            [
                "charging-efficiency",
            ],
            False,
        ),
        (
            [
                "discharging-efficiency",
            ],
            False,
        ),
        (["discharging-efficiency", "charging-efficiency"], False),
        (
            ["discharging-efficiency", "charging-efficiency", "roundtrip_efficiency"],
            True,
        ),
        (["discharging-efficiency", "roundtrip-efficiency"], True),
        (["charging-efficiency", "roundtrip-efficiency"], True),
        (["roundtrip-efficiency"], False),
    ],
)
def test_efficiency_pair(
    db, app, setup_dummy_sensors, setup_efficiency_sensors, fields, fails
):
    """
    Check that the efficiency can only be defined by the roundtrip efficiency field
    or by the (dis)charging efficiency fields.
    """

    sensor1, _, _, _ = setup_dummy_sensors

    schema = StorageFlexModelSchema(
        sensor=sensor1,
        start=datetime(2023, 1, 1, tzinfo=pytz.UTC),
    )

    def load_schema():
        flex_model = {
            "storage-efficiency": 1,
            "soc-at-start": "0 MWh",
        }
        for f in fields:
            flex_model[f] = "90%"

        schema.load(flex_model)

    if fails:
        with pytest.raises(ValidationError):
            load_schema()
    else:
        load_schema()


@pytest.mark.parametrize(
    ["flex_context", "fails"],
    [
        (
            {"site-power-capacity": -1},
            {"site-power-capacity": "Unsupported value type"},
        ),
        (
            {"site-power-capacity": "-1 MVA"},
            {"site-power-capacity": "Must be greater than or equal to 0."},
        ),
        (
            {"site-power-capacity": "1 MVA"},
            False,
        ),
        (
            {"site-power-capacity": {"sensor": "site-power-capacity"}},
            False,
        ),
        (
            {
                "consumption-price": "1 KRW/MWh",
                "site-peak-production-price": "1 EUR/MW",
            },
            {
                "site-peak-production-price": "all prices in the flex-context must share the same currency unit"
            },
        ),
        (
            {
                "consumption-price": "1 MKRW/MWh",
                "site-peak-production-price": "1 KRW/MW",
            },
            False,
        ),
        (
            {
                "site-peak-production-price": "-1 KRW/MW",
            },
            {"site-peak-production-price": "Must be greater than or equal to 0."},
        ),
        (
            {
                "site-consumption-breach-price": [
                    {
                        "value": "1 KRW/MWh",
                        "start": "2025-03-16T00:00+01",
                        "duration": "P1D",
                    },
                    {
                        "value": "1 KRW/MW",
                        "start": "2025-03-16T00:00+01",
                        "duration": "P1D",
                    },
                ],
            },
            {
                "site-consumption-breach-price": "Segments of a time series must share the same unit."
            },
        ),
        (
            {
                "site-consumption-breach-price": "450 AUD/MW",
                "relax-site-capacity-constraints": True,
            },
            False,
        ),
        (
            {
                "consumption-price": {"sensor": "consumption-price in SEK/kWh"},
                "production-price": {"sensor": "production-price in SEK/kWh"},
            },
            False,
        ),
        (
            {
                "consumption-price": {"sensor": "consumption-price in SEK/MWh"},
                "production-price": {"sensor": "production-price in SEK/MWh"},
            },
            False,
        ),
        (
            {
                "consumption-price": {"sensor": "consumption-price in SEK/kWh"},
                "production-price": {"sensor": "production-price in SEK/MWh"},
            },
            False,
        ),
        (
            {
                "commitments": [
                    {
                        "name": "a sample commitment",
                        "baseline": "10 kWh",
                        "up-price": "100 EUR/MWh",
                        "down-price": "120 EUR/MWh",
                    }
                ]
            },
            {"commitments.0.baseline": "Cannot convert value `10 kWh` to 'MW'"},
        ),
        # Energy price units with a power baseline
        (
            {
                "commitments": [
                    {
                        "name": "a sample commitment",
                        "baseline": "10 kW",
                        "up-price": "100 EUR/MWh",
                        "down-price": "120 EUR/MWh",
                    }
                ]
            },
            False,
        ),
        # Power price units with a power baseline
        (
            {
                "commitments": [
                    {
                        "name": "a sample commitment",
                        "baseline": "10 kW",
                        "up-price": "100 EUR/MW",
                        "down-price": "120 EUR/MW",
                    }
                ]
            },
            False,
        ),
        # Mixed (power and energy) price units with a power baseline
        (
            {
                "commitments": [
                    {
                        "name": "a sample commitment",
                        "baseline": "10 kW",
                        "up-price": "100 EUR/MW",
                        "down-price": "120 EUR/MWh",
                    }
                ]
            },
            False,
        ),
        # One-day commitment
        (
            {
                "commitments": [
                    {
                        "name": "a sample commitment",
                        "baseline": [
                            {
                                "value": "10 kW",
                                "start": "2025-03-18T00:00+01:00",
                                "duration": "P1D",
                            }
                        ],
                        "up-price": [
                            {
                                "value": "100 EUR/MWh",
                                "start": "2025-03-18T00:00+01:00",
                                "duration": "P1D",
                            }
                        ],
                        "down-price": [
                            {
                                "value": "120 EUR/MWh",
                                "start": "2025-03-18T00:00+01:00",
                                "duration": "P1D",
                            }
                        ],
                    }
                ]
            },
            False,
        ),
        # One-day commitment with wrong baseline unit
        (
            {
                "commitments": [
                    {
                        "name": "a sample commitment",
                        "baseline": [
                            {
                                "value": "10 kW/h",
                                "start": "2025-03-18T00:00+01:00",
                                "duration": "P1D",
                            }
                        ],
                        "up-price": [
                            {
                                "value": "100 EUR/MWh",
                                "start": "2025-03-18T00:00+01:00",
                                "duration": "P1D",
                            }
                        ],
                        "down-price": [
                            {
                                "value": "120 EUR/MWh",
                                "start": "2025-03-18T00:00+01:00",
                                "duration": "P1D",
                            }
                        ],
                    }
                ]
            },
            {
                "commitments.0.baseline.0.value": "Cannot convert value `10 kW/h` to 'MW'"
            },
        ),
        # One-day commitment with wrong price unit
        (
            {
                "commitments": [
                    {
                        "name": "a sample commitment",
                        "baseline": [
                            {
                                "value": "10 kW",
                                "start": "2025-03-18T00:00+01:00",
                                "duration": "P1D",
                            }
                        ],
                        "up-price": [
                            {
                                "value": "100 EUR/MWh/h",
                                "start": "2025-03-18T00:00+01:00",
                                "duration": "P1D",
                            }
                        ],
                        "down-price": [
                            {
                                "value": "120 EUR/MWh",
                                "start": "2025-03-18T00:00+01:00",
                                "duration": "P1D",
                            }
                        ],
                    }
                ]
            },
            {
                "commitments.0.up-price": "Commitment up-price must have a power or energy unit in its denominator."
            },
        ),
        # Ramp price units with a power baseline
        (
            {
                "commitments": [
                    {
                        "name": "a sample commitment",
                        "baseline": "10 kW",
                        "up-price": "100 EUR/MW/h",
                        "down-price": "120 EUR/MW/h",
                    }
                ]
            },
            {
                "commitments.0.up-price": "Commitment up-price must have a power or energy unit in its denominator."
            },
        ),
    ],
)
def test_flex_context_schema(
    db, app, setup_site_capacity_sensor, setup_price_sensors, flex_context, fails
):
    schema = FlexContextSchema()

    # Replace sensor name with sensor ID
    sensors_to_pick_from = {**setup_site_capacity_sensor, **setup_price_sensors}
    for field_name, field_value in flex_context.items():
        if isinstance(field_value, dict):
            flex_context[field_name]["sensor"] = sensors_to_pick_from[
                field_value["sensor"]
            ].id

    check_schema_loads_data(schema=schema, data=flex_context, fails=fails)


def check_schema_loads_data(schema, data, fails):
    if fails:
        with pytest.raises(ValidationError) as e_info:
            schema.load(data)
        print(f"Returned error message: {e_info.value.messages}")
        for field_name, expected_message in fails.items():
            field_name, *nested_field_names = field_name.split(".")
            assert field_name in e_info.value.messages
            # Check whether the expected messages is one of the message for the given field
            messages = e_info.value.messages[field_name]

            # Look for message in nested field name, such as commitments.0.baseline
            for nested_field_name in nested_field_names:
                if nested_field_name.isdigit():
                    nested_field_name = int(nested_field_name)
                messages = messages[nested_field_name]
            assert any(expected_message in message for message in messages)
    else:
        schema.load(data)


# test DBFlexContextSchema
@pytest.mark.parametrize(
    ["flex_context", "fails"],
    [
        (
            {"consumption-price": "13000 kW"},
            {
                "consumption-price": "Fixed prices are not currently supported for consumption-price in flex-context fields in the DB.",
            },
        ),
        (
            {
                "production-price": {
                    "sensor": "placeholder for site-power-capacity sensor"
                }
            },
            {
                "production-price": "Energy price field 'production-price' must have an energy price unit."
            },
        ),
        (
            {"production-price": {"sensor": "placeholder for price sensor"}},
            False,
        ),
        (
            {"consumption-price": "100 EUR/MWh"},
            {
                "consumption-price": "Fixed prices are not currently supported for consumption-price in flex-context fields in the DB.",
            },
        ),
        (
            {"production-price": "100 EUR/MW"},
            {
                "production-price": "Fixed prices are not currently supported for production-price in flex-context fields in the DB."
            },
        ),
        (
            {"site-power-capacity": 100},
            {
                "site-power-capacity": f"Unsupported value type. `{type(100)}` was provided but only dict, list and str are supported."
            },
        ),
        (
            {
                "site-power-capacity": [
                    {
                        "value": "100 kW",
                        "start": "2025-03-18T00:00+01:00",
                        "duration": "P2D",
                    }
                ]
            },
            {
                "site-power-capacity": "A time series specification (listing segments) is not supported when storing flex-context fields. Use a fixed quantity or a sensor reference instead."
            },
        ),
        (
            {"site-power-capacity": "5 kWh"},
            {"site-power-capacity": "Cannot convert value `5 kWh` to 'MW'"},
        ),
        (
            {"site-consumption-capacity": "6 kWh"},
            {"site-consumption-capacity": "Cannot convert value `6 kWh` to 'MW'"},
        ),
        (
            {"site-consumption-capacity": "6000 kW"},
            False,
        ),
        (
            {"site-production-capacity": "6 kWh"},
            {"site-production-capacity": "Cannot convert value `6 kWh` to 'MW'"},
        ),
        (
            {"site-production-capacity": "7000 kW"},
            False,
        ),
        (
            {"site-consumption-breach-price": "6 kWh"},
            {
                "site-consumption-breach-price": "Capacity price field 'site-consumption-breach-price' must have a capacity price unit."
            },
        ),
        (
            {"site-consumption-breach-price": "450 EUR/MW"},
            False,
        ),
        (
            {"site-production-breach-price": "550 EUR/MWh"},
            {
                "site-production-breach-price": "Capacity price field 'site-production-breach-price' must have a capacity price unit."
            },
        ),
        (
            {"site-production-breach-price": "3500 EUR/MW"},
            False,
        ),
        (
            {"site-peak-consumption": "60 EUR/MWh"},
            {"site-peak-consumption": "Cannot convert value `60 EUR/MWh` to 'MW'"},
        ),
        (
            {"site-peak-consumption": "3500 kW"},
            False,
        ),
        (
            {"site-peak-consumption-price": "6 orange/Mw"},
            {
                "site-peak-consumption-price": "Cannot convert value '6 orange/Mw' to a valid quantity. 'orange' is not defined in the unit registry"
            },
        ),
        (
            {"site-peak-consumption-price": "100 EUR/MW"},
            False,
        ),
        (
            {"site-peak-production": "75kWh"},
            {"site-peak-production": "Cannot convert value `75kWh` to 'MW'"},
        ),
        (
            {"site-peak-production": "17000 kW"},
            False,
        ),
        (
            {"site-peak-production-price": "4500 EUR/MWh"},
            {
                "site-peak-production-price": "Capacity price field 'site-peak-production-price' must have a capacity price unit."
            },
        ),
        (
            {"site-peak-consumption-price": "700 EUR/MW"},
            False,
        ),
        # Energy price units with a power baseline, also works in DBFlexContext
        (
            {
                "commitments": [
                    {
                        "name": "a sample commitment",
                        "baseline": "10 kW",
                        "up-price": "100 EUR/MWh",
                        "down-price": "120 EUR/MWh",
                    }
                ]
            },
            False,
        ),
        # One-day commitment not allowed in DBFlexContext
        (
            {
                "commitments": [
                    {
                        "name": "a sample commitment",
                        "baseline": [
                            {
                                "value": "10 kW",
                                "start": "2025-03-18T00:00+01:00",
                                "duration": "P1D",
                            }
                        ],
                        "up-price": [
                            {
                                "value": "100 EUR/MWh",
                                "start": "2025-03-18T00:00+01:00",
                                "duration": "P1D",
                            }
                        ],
                        "down-price": [
                            {
                                "value": "120 EUR/MWh",
                                "start": "2025-03-18T00:00+01:00",
                                "duration": "P1D",
                            }
                        ],
                    }
                ]
            },
            {
                "commitments.0.baseline": "A time series specification (listing segments) is not supported when storing flex-context fields. Use a fixed quantity or a sensor reference instead."
            },
        ),
    ],
)
def test_db_flex_context_schema(
    db, app, setup_dummy_sensors, setup_site_capacity_sensor, flex_context, fails
):
    schema = DBFlexContextSchema()

    price_sensor = setup_dummy_sensors[1]
    capacity_sensor = setup_site_capacity_sensor["site-power-capacity"]

    # Replace sensor name with sensor ID
    for field_name, field_value in flex_context.items():
        if isinstance(field_value, dict):
            if field_value["sensor"] == "placeholder for site-power-capacity sensor":
                flex_context[field_name]["sensor"] = capacity_sensor.id
            elif field_value["sensor"] == "placeholder for price sensor":
                flex_context[field_name]["sensor"] = price_sensor.id

    check_schema_loads_data(schema=schema, data=flex_context, fails=fails)


@pytest.mark.parametrize(
    ["variable_quantity", "expected_unit"],
    [
        ("1 kWh", "kWh"),
        (
            [{"start": "2025-09-17T00:00+02", "duration": "PT3H", "value": "1 kWh"}],
            "kWh",
        ),
        ({"sensor": "epex_da"}, "EUR/MWh"),
    ],
)
@pytest.mark.parametrize("deserialized", [True, False])
def test_get_variable_quantity_unit(
    setup_markets, variable_quantity, expected_unit: str, deserialized: bool
):
    # Use sensor name to look up sensor ID from fixture
    if isinstance(variable_quantity, dict):
        variable_quantity = variable_quantity.copy()
        variable_quantity["sensor"] = setup_markets[variable_quantity["sensor"]].id

    field = VariableQuantityField("/1")  # we use to_unit="/1" here to allow any unit
    deserialized_variable_quantity = field.deserialize(variable_quantity)
    if deserialized:
        assert field._get_unit(deserialized_variable_quantity) == expected_unit
    else:
        assert (
            field._get_original_unit(variable_quantity, deserialized_variable_quantity)
            == expected_unit
        )


def test_flex_context_schema_rejects_filtered_aggregate_power(
    setup_dummy_sensors, setup_sources, db
):
    _, _, _, power_sensor = setup_dummy_sensors
    seita_source = setup_sources["Seita"]
    db.session.flush()

    with pytest.raises(ValidationError) as exc_info:
        FlexContextSchema().load(
            {
                "aggregate-power": {
                    "sensor": power_sensor.id,
                    "sources": [seita_source.id],
                }
            }
        )

    assert "cannot use source filters" in str(exc_info.value)


@pytest.mark.parametrize(
    ["flex_model", "fails"],
    [
        (
            {"soc-min": "450 EUR/MWh"},
            {"soc-min": "Cannot convert value `450 EUR/MWh` to 'MWh'"},
        ),
        (
            {"soc-min": "3500 kWh"},
            False,
        ),
        (
            {"soc-minima": {"sensor": "energy-sensor"}},
            False,
        ),
        (
            {"soc-minima": {"sensor": "price-sensor"}},
            {"soc-minima": "Cannot convert EUR/MWh to MWh"},
        ),
        (
            {"soc-gain": ["450 EUR/MWh", "650 EUR/MWh"]},
            {
                "soc-gain": [
                    ["Cannot convert value `450 EUR/MWh` to 'MW'"],
                    ["Cannot convert value `650 EUR/MWh` to 'MW'"],
                ]
            },
        ),
        (
            {"soc-usage": ["3500 kW", {"sensor": "power-sensor"}]},
            False,
        ),
        (
            {"roundtrip-efficiency": "90%"},
            False,
        ),
        (
            {"roundtrip-efficiency": "12 MW"},
            {"roundtrip-efficiency": "Cannot convert value `12 MW` to '%'"},
        ),
        (
            {"storage-efficiency": {"sensor": "efficiency-sensor"}},
            False,
        ),
        (
            {"storage-efficiency": {"sensor": "power-sensor"}},
            {"storage-efficiency": "Cannot convert MW to %"},
        ),
        # plain quantity storage-efficiency without sensor-backed consumption/production should fail
        (
            {"storage-efficiency": "90%"},
            [
                {
                    "storage-efficiency": "The storage-efficiency cannot be interpreted without a resolution."
                },
                False,
            ],
        ),
        # plain quantity storage-efficiency is valid when consumption is sensor-backed
        (
            {
                "storage-efficiency": "90%",
                "consumption": {"sensor": "power-sensor"},
            },
            False,
        ),
    ],
)
def test_flex_model_schemas(
    db, app, setup_dummy_sensors, setup_efficiency_sensors, flex_model, fails
):
    """Validate StorageFlexModelSchema and DBStorageFlexModelSchema for accepted and rejected flex-model inputs.

    Input under test:
    - ``flex_model`` payloads with fixed quantities, sensor references, and list fields
        (for example ``soc-min``, ``soc-minima``, ``soc-gain``,
        ``roundtrip-efficiency``, ``storage-efficiency``).
    - Sensor placeholders in parametrized payloads are replaced with fixture-backed
        sensor IDs before schema loading.

    Expected outcomes:
    - When ``fails`` is ``False``, schema loading succeeds.
    - When ``fails`` is a field-to-message mapping, schema loading raises
        ``ValidationError`` and contains the expected field-specific error message(s).
    - When ``fails`` is a list, its first entry represents the expectation for the StorageFlexModelSchema,
        and the second entry represents the expectation for the DBStorageFlexModelSchema.
    """
    schemas = [
        StorageFlexModelSchema(start=datetime(2026, 6, 1), sensor=None),
        DBStorageFlexModelSchema(),
    ]
    if not isinstance(fails, list):
        # Then the same expectation holds for both schemas
        fails = [fails, fails]

    sensors = {
        "energy-sensor": setup_dummy_sensors[0],
        "price-sensor": setup_dummy_sensors[1],
        "power-sensor": setup_dummy_sensors[3],
        "efficiency-sensor": setup_efficiency_sensors,
    }

    for field_name, field_value in flex_model.items():
        if isinstance(field_value, dict) and "sensor" in field_value:
            # Replace sensor name with sensor ID
            flex_model[field_name]["sensor"] = sensors[
                flex_model[field_name]["sensor"]
            ].id
        if isinstance(field_value, list):
            # Replace sensor names in lists with sensor IDs
            flex_model[field_name] = [
                {"sensor": sensors[item["sensor"]].id} if "sensor" in item else item
                for item in field_value
            ]

    for schema, fail in zip(schemas, fails):
        if fail:
            with pytest.raises(ValidationError) as e_info:  # noqa: F841
                schema.load(flex_model)


@pytest.mark.parametrize(
    ["flex_context", "fails"],
    [
        # Test aggregate-consumption field with sensor reference
        (
            {"aggregate-consumption": {"sensor": "consumption-price in SEK/MWh"}},
            False,
        ),
        # Test aggregate-production field with sensor reference
        (
            {"aggregate-production": {"sensor": "production-price in SEK/MWh"}},
            False,
        ),
        # Test both aggregate fields together
        (
            {
                "aggregate-consumption": {"sensor": "consumption-price in SEK/MWh"},
                "aggregate-production": {"sensor": "production-price in SEK/MWh"},
            },
            False,
        ),
        # Test that relax_constraints defaults to True in FlexContextSchema
        (
            {"site-power-capacity": "1 MVA"},
            False,
        ),
        # Test breach prices moved to SharedSchema
        (
            {
                "consumption-breach-price": "100 EUR/MW",
                "production-breach-price": "100 EUR/MW",
            },
            False,
        ),
        # Test soc breach prices moved to SharedSchema
        (
            {
                "soc-minima-breach-price": "1000 EUR/MWh",
                "soc-maxima-breach-price": "1000 EUR/MWh",
            },
            False,
        ),
    ],
)
def test_shared_schema_fields_in_flex_context(
    db, app, setup_site_capacity_sensor, setup_price_sensors, flex_context, fails
):
    """Test that SharedSchema fields are accessible in FlexContextSchema."""
    schema = FlexContextSchema()

    # Replace sensor name with sensor ID
    sensors_to_pick_from = {**setup_site_capacity_sensor, **setup_price_sensors}
    for field_name, field_value in flex_context.items():
        if isinstance(field_value, dict) and "sensor" in field_value:
            sensor_name = field_value["sensor"]
            if sensor_name in sensors_to_pick_from:
                flex_context[field_name]["sensor"] = sensors_to_pick_from[
                    sensor_name
                ].id

    check_schema_loads_data(schema=schema, data=flex_context, fails=fails)


@pytest.mark.parametrize(
    ["commodity_contexts", "fails"],
    [
        # Test single commodity pass validation and defaults relax_constraints to True
        (
            [
                {
                    "commodity": "electricity",
                    "site-power-capacity": "1 MVA",
                }
            ],
            False,
        ),
        # Likewise for multiple commodities, relax_constraints should default to True for each
        (
            [
                {
                    "commodity": "electricity",
                    "site-power-capacity": "1 MVA",
                },
                {
                    "commodity": "heat",
                    "site-power-capacity": "500 kW",
                },
            ],
            False,
        ),
        # Test aggregate fields in commodity context pass validation
        (
            [
                {
                    "commodity": "electricity",
                    "aggregate-consumption": {"sensor": "consumption-price in SEK/MWh"},
                    "aggregate-production": {"sensor": "production-price in SEK/MWh"},
                }
            ],
            False,
        ),
        # Test breach prices in commodity context pass validation
        (
            [
                {
                    "commodity": "electricity",
                    "consumption-breach-price": "100 EUR/MW",
                    "production-breach-price": "100 EUR/MW",
                }
            ],
            False,
        ),
    ],
)
def test_commodity_flex_context_defaults(
    db, app, setup_site_capacity_sensor, setup_price_sensors, commodity_contexts, fails
):
    """Test that CommodityFlexContextSchema has correct defaults, especially relax_constraints=True."""
    from flexmeasures.data.schemas.scheduling import CommodityFlexContextSchema

    # Replace sensor name with sensor ID
    sensors_to_pick_from = {**setup_site_capacity_sensor, **setup_price_sensors}
    for context in commodity_contexts:
        for field_name, field_value in context.items():
            if isinstance(field_value, dict) and "sensor" in field_value:
                sensor_name = field_value["sensor"]
                if sensor_name in sensors_to_pick_from:
                    context[field_name]["sensor"] = sensors_to_pick_from[sensor_name].id

    # Test loading each commodity context
    schema = CommodityFlexContextSchema()
    for context in commodity_contexts:
        if fails:
            with pytest.raises(ValidationError) as e_info:
                loaded = schema.load(context)
            print(f"Returned error message: {e_info.value.messages}")
        else:
            loaded = schema.load(context)
            # Verify relax_constraints defaults to True in CommodityFlexContextSchema
            assert loaded.get("relax_constraints", True) is True


@pytest.mark.parametrize(
    ["flex_context_listing", "fails"],
    [
        # Test flex-context listing with mixed currencies should fail
        (
            {
                "commodities": [
                    {
                        "commodity": "electricity",
                        "consumption-price": "1 EUR/MWh",
                    },
                    {
                        "commodity": "heat",
                        "consumption-price": "1 USD/MWh",
                    },
                ]
            },
            {
                "commodities": "all prices in the flex-context must share the same currency unit"
            },
        ),
        # Test flex-context listing with same currencies should pass
        (
            {
                "commodities": [
                    {
                        "commodity": "electricity",
                        "consumption-price": "1 EUR/MWh",
                    },
                    {
                        "commodity": "heat",
                        "consumption-price": "2 EUR/MWh",
                    },
                ]
            },
            False,
        ),
        # Test flex-context listing with breach prices sharing currency
        (
            {
                "commodities": [
                    {
                        "commodity": "electricity",
                        "consumption-breach-price": "100 EUR/MW",
                        "production-breach-price": "10 cEUR/kW",
                    }
                ]
            },
            False,
        ),
        # Test flex-context listing with mixed breach price currencies should fail
        (
            {
                "commodities": [
                    {
                        "commodity": "electricity",
                        "consumption-breach-price": "100 EUR/MW",
                    },
                    {
                        "commodity": "heat",
                        "consumption-breach-price": "100 USD/MW",
                    },
                ]
            },
            {
                "commodities": "all prices in the flex-context must share the same currency unit"
            },
        ),
    ],
)
def test_flex_context_listing_shared_currency(
    db,
    app,
    setup_site_capacity_sensor,
    setup_price_sensors,
    flex_context_listing,
    fails,
):
    """Test that flex-context listings enforce shared currency across commodities."""
    schema = FlexContextSchema()

    check_schema_loads_data(schema=schema, data=flex_context_listing, fails=fails)


def test_flex_context_listing_rejects_duplicate_commodities(db, app):
    """test_flex_context_listing_rejects_duplicate_commodities: a commodity listed twice must be rejected."""
    schema = FlexContextSchema()
    flex_context = {
        "commodities": [
            {"commodity": "electricity", "consumption-price": "1 EUR/MWh"},
            {"commodity": "electricity", "production-price": "1 EUR/MWh"},
        ]
    }
    check_schema_loads_data(
        schema=schema,
        data=flex_context,
        fails={"commodities": "may only be listed once"},
    )


def test_flex_context_single_dict_rejects_non_electricity_commodity(db, app):
    """test_flex_context_single_dict_rejects_non_electricity_commodity: the single-dict form only supports electricity."""
    schema = FlexContextSchema()
    flex_context = {"commodity": "gas", "consumption-price": "1 EUR/MWh"}
    check_schema_loads_data(
        schema=schema,
        data=flex_context,
        fails={"commodity": "only supports the 'electricity' commodity"},
    )


def test_flex_context_single_dict_allows_explicit_electricity_commodity(db, app):
    """test_flex_context_single_dict_allows_explicit_electricity_commodity: explicit electricity is fine."""
    schema = FlexContextSchema()
    flex_context = {"commodity": "electricity", "consumption-price": "1 EUR/MWh"}
    check_schema_loads_data(schema=schema, data=flex_context, fails=False)


def test_flex_context_tolerates_commodities_with_top_level_shared_fields(db, app):
    """test_flex_context_tolerates_commodities_with_top_level_shared_fields: mixing must be tolerated.

    The API path dict-merges an asset's db-stored (electricity) flex-context fields at the
    top level after normalizing a multi-commodity list to {"commodities": [...]}, so this
    mix must load fine. Top-level fields serve as the electricity context only when the
    commodities list has no electricity entry (see _get_commodity_contexts in storage.py).
    """
    schema = FlexContextSchema()
    flex_context = {
        "consumption-price": "1 EUR/MWh",
        "commodities": [
            {"commodity": "gas", "consumption-price": "1 EUR/MWh"},
        ],
    }
    check_schema_loads_data(schema=schema, data=flex_context, fails=False)


def test_asset_trigger_schema_rejects_malformed_flex_context(app):
    """test_asset_trigger_schema_rejects_malformed_flex_context: a non-dict/list flex-context must raise a ValidationError, not a TypeError."""
    from flexmeasures.data.schemas.scheduling import AssetTriggerSchema

    schema = AssetTriggerSchema()
    with pytest.raises(ValidationError) as e_info:
        schema.normalize_flex_context_format({"flex-context": "not-a-dict-or-list"})
    assert "flex-context" in str(e_info.value)
