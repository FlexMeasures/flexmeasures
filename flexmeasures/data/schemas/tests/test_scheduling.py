from datetime import datetime
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
from flexmeasures.data.schemas.sensors import (
    TimedEventSchema,
    VariableQuantityField,
    SensorReference,
)
from flexmeasures.utils.unit_utils import ur


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


def test_storage_flex_model_schema_preserves_off_tick_soc_datetimes(
    db, app, setup_dummy_sensors
):
    sensor1, _, _, _ = setup_dummy_sensors

    schema = StorageFlexModelSchema(
        sensor=sensor1,
        start=datetime(2023, 1, 1, tzinfo=pytz.UTC),
    )

    flex_model = schema.load(
        {
            "soc-at-start": "0 MWh",
            "soc-targets": [
                {"datetime": "2023-01-01T00:04:40+00:00", "value": "1 MWh"}
            ],
        }
    )

    assert flex_model["soc_targets"][0]["datetime"] == pd.Timestamp(
        "2023-01-01T00:04:40+00:00"
    )


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
        # Commitment prices must share the flex-context's currency
        (
            {
                "consumption-price": "100 EUR/MWh",
                "commitments": [
                    {
                        "name": "a sample commitment",
                        "baseline": "10 kW",
                        "up-price": "100 USD/MWh",
                    }
                ],
            },
            {
                "commitments": "all prices in the flex-context must share the same currency unit"
            },
        ),
        # Commitment prices sharing the flex-context's currency are fine
        (
            {
                "consumption-price": "100 EUR/MWh",
                "commitments": [
                    {
                        "name": "a sample commitment",
                        "baseline": "10 kW",
                        "up-price": "100 EUR/MWh",
                        "down-price": "0.12 EUR/kWh",
                    }
                ],
            },
            False,
        ),
        # Commitments can also set the shared currency (mixed currencies still fail)
        (
            {
                "commitments": [
                    {
                        "name": "a sample commitment",
                        "baseline": "10 kW",
                        "up-price": "100 USD/MWh",
                        "down-price": "120 EUR/MWh",
                    }
                ]
            },
            {
                "commitments": "all prices in the flex-context must share the same currency unit"
            },
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
        # Commitment without a baseline
        (
            {
                "commitments": [
                    {
                        "name": "a sample commitment",
                        "up-price": "100 EUR/MWh",
                    }
                ]
            },
            {"commitments.0.baseline": "A commitment requires a baseline."},
        ),
        # Commitment with an empty name
        (
            {
                "commitments": [
                    {
                        "name": "",
                        "baseline": "10 kW",
                        "up-price": "100 EUR/MWh",
                    }
                ]
            },
            {"commitments.0.name": "Shorter than minimum length 1."},
        ),
        # Commitment without any deviation price
        (
            {
                "commitments": [
                    {
                        "name": "a sample commitment",
                        "baseline": "10 kW",
                    }
                ]
            },
            {
                "commitments.0.up-price": "A commitment requires at least one deviation price (up-price and/or down-price)."
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


def test_flex_context_schema_relaxes_soc_constraints_by_default():
    loaded_flex_context = FlexContextSchema().load({"consumption-price": "1 EUR/MWh"})

    assert loaded_flex_context["relax_constraints"] is True
    # The specific flag is not set, so the umbrella flag decides.
    assert loaded_flex_context["relax_soc_constraints"] is None
    assert loaded_flex_context["soc_minima_breach_price"].to(
        "EUR/MWh"
    ).magnitude == pytest.approx(1_000_000)
    assert loaded_flex_context["soc_maxima_breach_price"].to(
        "EUR/MWh"
    ).magnitude == pytest.approx(1_000_000)


def test_flex_context_schema_preserves_explicit_soc_breach_prices():
    loaded_flex_context = FlexContextSchema().load(
        {
            "consumption-price": "1 EUR/MWh",
            "soc-minima-breach-price": "5 EUR/kWh",
            "soc-maxima-breach-price": "7 EUR/kWh",
        }
    )

    assert loaded_flex_context["soc_minima_breach_price"].to(
        "EUR/kWh"
    ).magnitude == pytest.approx(5)
    assert loaded_flex_context["soc_maxima_breach_price"].to(
        "EUR/kWh"
    ).magnitude == pytest.approx(7)


def test_flex_context_schema_umbrella_opt_out_disables_soc_relaxation():
    """Setting relax-constraints to False alone keeps SoC minima/maxima hard."""
    loaded_flex_context = FlexContextSchema().load(
        {"consumption-price": "1 EUR/MWh", "relax-constraints": False}
    )

    assert "soc_minima_breach_price" not in loaded_flex_context
    assert "soc_maxima_breach_price" not in loaded_flex_context
    assert "consumption_breach_price" not in loaded_flex_context
    assert "ems_consumption_breach_price" not in loaded_flex_context


def test_flex_context_schema_explicit_soc_relaxation_overrides_umbrella_opt_out():
    """An explicit relax-soc-constraints wins over an explicit relax-constraints."""
    loaded_flex_context = FlexContextSchema().load(
        {
            "consumption-price": "1 EUR/MWh",
            "relax-constraints": False,
            "relax-soc-constraints": True,
        }
    )

    assert loaded_flex_context["soc_minima_breach_price"].to(
        "EUR/MWh"
    ).magnitude == pytest.approx(1_000_000)

    loaded_flex_context = FlexContextSchema().load(
        {"consumption-price": "1 EUR/MWh", "relax-soc-constraints": False}
    )

    assert "soc_minima_breach_price" not in loaded_flex_context
    assert "soc_maxima_breach_price" not in loaded_flex_context


def test_flex_context_schema_explicit_site_capacity_relaxation_overrides_umbrella():
    """An explicit relax-site-capacity-constraints wins over relax-constraints, in both directions."""
    # Explicit opt-out beats the umbrella default of True.
    loaded_flex_context = FlexContextSchema().load(
        {
            "consumption-price": "1 EUR/MWh",
            "relax-site-capacity-constraints": False,
        }
    )

    assert "ems_consumption_breach_price" not in loaded_flex_context
    assert "ems_production_breach_price" not in loaded_flex_context

    # Explicit opt-in beats an explicit umbrella opt-out.
    loaded_flex_context = FlexContextSchema().load(
        {
            "consumption-price": "1 EUR/MWh",
            "relax-constraints": False,
            "relax-site-capacity-constraints": True,
        }
    )

    assert loaded_flex_context["ems_consumption_breach_price"].to(
        "EUR/kW"
    ).magnitude == pytest.approx(10_000)
    assert loaded_flex_context["ems_production_breach_price"].to(
        "EUR/kW"
    ).magnitude == pytest.approx(10_000)


def test_flex_context_schema_fills_default_breach_prices_per_field():
    """Setting one breach price of a pair explicitly still fills the default for the other."""
    loaded_flex_context = FlexContextSchema().load(
        {
            "consumption-price": "1 EUR/MWh",
            "soc-minima-breach-price": "5 EUR/kWh",
        }
    )

    assert loaded_flex_context["soc_minima_breach_price"].to(
        "EUR/kWh"
    ).magnitude == pytest.approx(5)
    assert loaded_flex_context["soc_maxima_breach_price"].to(
        "EUR/kWh"
    ).magnitude == pytest.approx(1_000)

    loaded_flex_context = FlexContextSchema().load(
        {
            "consumption-price": "1 EUR/MWh",
            "site-consumption-breach-price": "3 EUR/kW",
        }
    )

    assert loaded_flex_context["ems_consumption_breach_price"].to(
        "EUR/kW"
    ).magnitude == pytest.approx(3)
    assert loaded_flex_context["ems_production_breach_price"].to(
        "EUR/kW"
    ).magnitude == pytest.approx(10_000)

    # The device capacity pair is deliberately not filled per field:
    # see test_explicit_device_breach_price_is_not_overwritten.


def test_db_flex_context_schema_fills_no_default_breach_prices():
    """Validating a stored flex-context does not bake in the default breach prices implied by the relax flags."""
    loaded_flex_context = DBFlexContextSchema().load({})

    assert "soc_minima_breach_price" not in loaded_flex_context
    assert "soc_maxima_breach_price" not in loaded_flex_context
    assert "ems_consumption_breach_price" not in loaded_flex_context
    assert "ems_production_breach_price" not in loaded_flex_context

    # Not even when relaxation is asked for explicitly in the stored flex-context.
    loaded_flex_context = DBFlexContextSchema().load({"relax-constraints": True})

    assert "soc_minima_breach_price" not in loaded_flex_context
    assert "ems_consumption_breach_price" not in loaded_flex_context


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
                "site-power-capacity": f"Unsupported value type. `{type(100)}` was provided but only dict, list, str, pint Quantity, tuple, and numeric values with a default source unit are supported."
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
        # group must reference a power sensor
        (
            {"group": {"sensor": "power-sensor"}},
            False,
        ),
        (
            {"group": {"sensor": "energy-sensor"}},
            {"group": "The `group` field must reference a sensor with a power unit."},
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
        StorageFlexModelSchema(
            start=datetime(2026, 6, 1, tzinfo=pytz.utc), sensor=None
        ),
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


def test_storage_flex_model_group_field(db, app, setup_dummy_sensors, dummy_asset):
    """The `group` field should load a `{"sensor": <id>}` reference to a power Sensor,
    reject non-power sensors, and reject unknown sensor IDs."""
    energy_sensor, _, _, power_sensor = setup_dummy_sensors

    for schema in (
        StorageFlexModelSchema(
            start=datetime(2026, 6, 1, tzinfo=pytz.UTC), sensor=None
        ),
        DBStorageFlexModelSchema(),
    ):
        # Valid group reference loads to a Sensor
        flex_model = schema.load({"group": {"sensor": power_sensor.id}})
        assert flex_model["group"]["sensor"] == power_sensor

        # A non-power sensor is rejected
        with pytest.raises(ValidationError, match="power unit"):
            schema.load({"group": {"sensor": energy_sensor.id}})

        # An unknown sensor ID is rejected (by SensorIdField)
        with pytest.raises(ValidationError, match="No sensor found"):
            schema.load({"group": {"sensor": -1}})

        # A valid asset reference loads to a GenericAsset
        flex_model = schema.load({"group": {"asset": dummy_asset.id}})
        assert flex_model["group"]["asset"] == dummy_asset

        # Both sensor and asset given: rejected
        with pytest.raises(ValidationError, match="exactly one"):
            schema.load({"group": {"sensor": power_sensor.id, "asset": dummy_asset.id}})

        # Neither sensor nor asset given: rejected
        with pytest.raises(ValidationError, match="exactly one"):
            schema.load({"group": {}})


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


def _assert_quantity_or_none(actual, expected):
    """Compare an (optionally None) ur.Quantity against an expected ur.Quantity or None."""
    if expected is None:
        assert actual is None
    else:
        assert actual is not None
        assert actual.to(expected.units).magnitude == pytest.approx(expected.magnitude)


@pytest.mark.parametrize(
    ["context_input", "expected"],
    [
        # Case 1: none of the 5 grid-connection fields given -> fully disconnected
        # commodity. Both site capacities default to 0 as *soft* constraints (a
        # default breach price is filled in); site-power-capacity stays unlimited.
        (
            {"commodity": "gas"},
            {
                "ems_consumption_capacity_in_mw": ur.Quantity("0 MW"),
                "ems_production_capacity_in_mw": ur.Quantity("0 MW"),
                "ems_power_capacity_in_mw": None,
                "consumption_price": ur.Quantity("0 EUR/MWh"),
                "ems_consumption_breach_price_set": True,
                "ems_production_breach_price_set": True,
            },
        ),
        # Case 2: only consumption-price given -> assume a grid connection for
        # consumption (unlimited site-power/consumption-capacity); 0
        # site-production-capacity (soft).
        (
            {"commodity": "gas", "consumption-price": "10 EUR/MWh"},
            {
                "ems_consumption_capacity_in_mw": None,
                "ems_production_capacity_in_mw": ur.Quantity("0 MW"),
                "ems_power_capacity_in_mw": None,
                "consumption_price": ur.Quantity("10 EUR/MWh"),
                "ems_production_breach_price_set": True,
            },
        ),
        # Case 3: only production-price given -> mirror image of case 2.
        (
            {"commodity": "gas", "production-price": "10 EUR/MWh"},
            {
                "ems_consumption_capacity_in_mw": ur.Quantity("0 MW"),
                "ems_production_capacity_in_mw": None,
                "ems_power_capacity_in_mw": None,
                "consumption_price": ur.Quantity("0 EUR/MWh"),
                "production_price": ur.Quantity("10 EUR/MWh"),
                "ems_consumption_breach_price_set": True,
            },
        ),
        # Case 4: only site-consumption-capacity given -> unlimited
        # site-power-capacity, 0 consumption-price, 0 site-production-capacity
        # (soft), (and thereby 0 production-price).
        (
            {"commodity": "gas", "site-consumption-capacity": "5 MW"},
            {
                "ems_consumption_capacity_in_mw": ur.Quantity("5 MW"),
                "ems_production_capacity_in_mw": ur.Quantity("0 MW"),
                "ems_power_capacity_in_mw": None,
                "consumption_price": ur.Quantity("0 EUR/MWh"),
                "ems_production_breach_price_set": True,
            },
        ),
        # Case 5: only site-production-capacity given -> mirror image of case 4.
        (
            {"commodity": "gas", "site-production-capacity": "5 MW"},
            {
                "ems_consumption_capacity_in_mw": ur.Quantity("0 MW"),
                "ems_production_capacity_in_mw": ur.Quantity("5 MW"),
                "ems_power_capacity_in_mw": None,
                "consumption_price": ur.Quantity("0 EUR/MWh"),
                "production_price": ur.Quantity("0 EUR/MWh"),
                "ems_consumption_breach_price_set": True,
            },
        ),
        # Case 6: only site-power-capacity given -> a *hard* constraint at that
        # capacity (both site capacities set equal to it; no breach price filled
        # in); 0 consumption- and production-price.
        (
            {"commodity": "gas", "site-power-capacity": "5 MW"},
            {
                "ems_consumption_capacity_in_mw": ur.Quantity("5 MW"),
                "ems_production_capacity_in_mw": ur.Quantity("5 MW"),
                "ems_power_capacity_in_mw": ur.Quantity("5 MW"),
                "consumption_price": ur.Quantity("0 EUR/MWh"),
                "production_price": ur.Quantity("0 EUR/MWh"),
                "ems_consumption_breach_price_set": False,
                "ems_production_breach_price_set": False,
            },
        ),
        # A multi-field combination: consumption-price given together with an
        # explicit site-power-capacity. The site-power-capacity is not the *sole*
        # field given, so it does not trigger the hard-constraint case; instead,
        # each direction is filled in independently: consumption-price given ->
        # site-consumption-capacity stays unlimited (implicitly bounded by
        # site-power-capacity at the scheduler level); production side untouched
        # -> 0 site-production-capacity (soft).
        (
            {
                "commodity": "gas",
                "consumption-price": "10 EUR/MWh",
                "site-power-capacity": "5 MW",
            },
            {
                "ems_consumption_capacity_in_mw": None,
                "ems_production_capacity_in_mw": ur.Quantity("0 MW"),
                "ems_power_capacity_in_mw": ur.Quantity("5 MW"),
                "consumption_price": ur.Quantity("10 EUR/MWh"),
                "ems_production_breach_price_set": True,
            },
        ),
    ],
)
def test_commodity_flex_context_smart_defaults(context_input, expected):
    """Test the smarter defaults for commodity contexts (see
    CommodityFlexContextSchema.fill_grid_connection_defaults).

    These are DB-free, direct schema loads (no sensors involved).
    """
    from flexmeasures.data.schemas.scheduling import CommodityFlexContextSchema

    loaded = CommodityFlexContextSchema().load(context_input)

    for field in (
        "ems_consumption_capacity_in_mw",
        "ems_production_capacity_in_mw",
        "ems_power_capacity_in_mw",
        "consumption_price",
        "production_price",
    ):
        if field in expected:
            _assert_quantity_or_none(loaded.get(field), expected[field])

    if "ems_consumption_breach_price_set" in expected:
        assert (loaded.get("ems_consumption_breach_price") is not None) == expected[
            "ems_consumption_breach_price_set"
        ]
    if "ems_production_breach_price_set" in expected:
        assert (loaded.get("ems_production_breach_price") is not None) == expected[
            "ems_production_breach_price_set"
        ]


@pytest.mark.parametrize(
    ["context_input", "expected_is_internal_node"],
    [
        # No grid-connection signal at all -> internal node.
        ({"commodity": "gas"}, True),
        # A price declares a grid connection -> not an internal node.
        ({"commodity": "gas", "consumption-price": "10 EUR/MWh"}, False),
        # A capacity field also declares a grid connection, even without any price,
        # since its prices get smart-defaulted to zero.
        # This must NOT be flagged as an internal node --
        # otherwise the scheduler would skip EMS constraints,
        # and force a per-step balance for a genuinely grid-connected commodity.
        ({"commodity": "gas", "site-consumption-capacity": "5 MW"}, False),
        ({"commodity": "gas", "site-production-capacity": "5 MW"}, False),
        ({"commodity": "gas", "site-power-capacity": "5 MW"}, False),
    ],
)
def test_commodity_flex_context_internal_node_flag(
    context_input, expected_is_internal_node
):
    """A commodity is an internal node only when the user gave neither prices nor any capacity/grid-connection field.

    See CommodityFlexContextSchema.fill_grid_connection_defaults.
    """
    from flexmeasures.data.schemas.scheduling import CommodityFlexContextSchema

    loaded = CommodityFlexContextSchema().load(context_input)

    assert loaded.get("is_internal_node", False) == expected_is_internal_node


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


def test_flex_context_listing_tolerates_price_free_context_in_other_currency():
    """test_flex_context_listing_tolerates_price_free_context_in_other_currency:
    a bare (price-free) commodity context must not trip the shared-currency check
    against a differently-currencied portfolio, since it has no user-given prices
    of its own -- its 0-price/breach-price fills should just inherit the
    portfolio's real currency.
    """
    schema = FlexContextSchema()

    # Case A: top-level price sets the portfolio currency.
    loaded = schema.load(
        {
            "consumption-price": "10 USD/MWh",
            "commodities": [
                {"commodity": "electricity", "consumption-price": "10 USD/MWh"},
                {"commodity": "gas"},
            ],
        }
    )
    assert loaded["shared_currency_unit"] == "USD"
    gas_context = next(
        c for c in loaded["commodity_contexts"] if c["commodity"] == "gas"
    )
    assert gas_context["shared_currency_unit"] == "USD"
    assert str(gas_context["consumption_price"].units) == "USD/MWh"

    # Case B: no top-level price; a sibling commodity context sets the currency.
    loaded = schema.load(
        {
            "commodities": [
                {"commodity": "electricity", "consumption-price": "10 USD/MWh"},
                {"commodity": "gas"},
            ],
        }
    )
    assert loaded["shared_currency_unit"] == "USD"
    gas_context = next(
        c for c in loaded["commodity_contexts"] if c["commodity"] == "gas"
    )
    assert gas_context["shared_currency_unit"] == "USD"
    assert str(gas_context["consumption_price"].units) == "USD/MWh"

    # Case C: no price given anywhere -> falls back to EUR everywhere.
    loaded = schema.load({"commodities": [{"commodity": "gas"}]})
    assert loaded["shared_currency_unit"] == "EUR"
    gas_context = loaded["commodity_contexts"][0]
    assert gas_context["shared_currency_unit"] == "EUR"

    # A genuine mismatch (both contexts have explicit, different currencies) must
    # still be rejected.
    check_schema_loads_data(
        schema=schema,
        data={
            "consumption-price": "10 USD/MWh",
            "commodities": [
                {"commodity": "electricity", "consumption-price": "10 USD/MWh"},
                {"commodity": "gas", "consumption-price": "10 EUR/MWh"},
            ],
        },
        fails={
            "commodities": "all prices in the flex-context must share the same currency unit"
        },
    )


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


@pytest.mark.parametrize(
    "capacity_fields, fails",
    [
        # Input device: production blocked, direction is unambiguous
        ({"production-capacity": "0 kW"}, False),
        # Output device: consumption blocked, direction is unambiguous
        ({"consumption-capacity": "0 kW"}, False),
        # Output device with a bounded input side still has one blocked direction
        ({"consumption-capacity": "5 kW", "production-capacity": "0 kW"}, False),
        # Smart default: only a consumption-capacity given -> input device
        # (production defaults to zero), no explicit zero needed.
        ({"consumption-capacity": "5 kW"}, False),
        # Smart default: only a production-capacity given -> output device
        # (consumption defaults to zero), no explicit zero needed.
        ({"production-capacity": "5 kW"}, False),
        # Neither direction given: ambiguous
        ({}, True),
        # Both directions open: ambiguous
        ({"consumption-capacity": "5 kW", "production-capacity": "5 kW"}, True),
        # Both directions blocked: degenerate (device pinned to zero flow)
        ({"consumption-capacity": "0 kW", "production-capacity": "0 kW"}, True),
    ],
)
def test_coupling_direction_must_be_unambiguous(app, capacity_fields, fails):
    """A device with a `coupling` field must have an unambiguous flow direction.

    The direction is inferred from which directional capacity is given (the opposite direction defaults to zero),
    so the sign of its coupling coefficient can be inferred.
    """
    schema = StorageFlexModelSchema(
        start=datetime(2026, 6, 1, tzinfo=pytz.utc), sensor=None
    )
    flex_model = {
        "power-capacity": "20 kW",
        "coupling": "chp",
        "coupling-coefficient": 0.5,
        **capacity_fields,
    }
    if fails:
        with pytest.raises(ValidationError) as e_info:
            schema.load(flex_model)
        assert "unambiguous flow direction" in str(e_info.value)
    else:
        schema.load(flex_model)


def test_uncoupled_device_needs_no_directional_capacities(app):
    """The coupling-direction check only applies to devices that define a `coupling` field."""
    schema = StorageFlexModelSchema(
        start=datetime(2026, 6, 1, tzinfo=pytz.utc), sensor=None
    )
    schema.load({"power-capacity": "20 kW"})


@pytest.mark.parametrize("blank_name", ["", " ", "\t", "  \n "])
def test_blank_coupling_name_is_rejected(app, blank_name):
    """A provided coupling name must contain at least one non-whitespace character.

    Otherwise unrelated devices could be silently coupled under an empty group key.
    This holds for both the scheduling schema and the db-stored one.
    """
    scheduling_flex_model = {
        "power-capacity": "20 kW",
        "production-capacity": "0 kW",
        "coupling": blank_name,
    }
    with pytest.raises(ValidationError) as e_info:
        StorageFlexModelSchema(
            start=datetime(2026, 6, 1, tzinfo=pytz.utc), sensor=None
        ).load(scheduling_flex_model)
    assert "non-empty" in str(e_info.value)

    with pytest.raises(ValidationError) as e_info:
        DBStorageFlexModelSchema().load({"coupling": blank_name})
    assert "non-empty" in str(e_info.value)


def test_db_flex_model_coupling_round_trips(app):
    """A db-stored flex-model accepts `coupling`/`coupling-coefficient` and round-trips them.

    Such flex-models are validated via DBStorageFlexModelSchema, e.g. by patch_asset.
    """
    schema = DBStorageFlexModelSchema()
    flex_model = {
        "coupling": "chp",
        "coupling-coefficient": 0.5,
    }
    loaded = schema.load(flex_model)
    assert loaded["coupling"] == "chp"
    assert loaded["coupling_coefficient"] == 0.5
    # coupling-coefficient must be strictly positive
    with pytest.raises(ValidationError):
        schema.load({"coupling": "chp", "coupling-coefficient": 0})


# Note: AssetTriggerSchema itself no longer aliases legacy field names (e.g.
# force_new_job_creation) -- that's v3_0-specific backward compatibility,
# layered on top by AssetTriggerSchemaV3 in flexmeasures/api/v3_0/assets.py,
# and tested there (flexmeasures/api/v3_0/tests/test_asset_trigger_schema_v3.py).
# This schema stays canonical since it's also used outside the API, e.g. by
# the CLI.


@pytest.mark.parametrize(
    ["flex_context", "fails"],
    [
        # Sensors under the field matching their explicit attribute, or without one
        (
            {
                "inflexible-consumption": [{"sensor": "consumption-positive power"}],
                "inflexible-production": [
                    {"sensor": "production-positive power"},
                    {"sensor": "attributeless power"},
                ],
            },
            None,
        ),
        # Source filters are allowed
        (
            {
                "inflexible-production": [
                    {
                        "sensor": "attributeless power",
                        "exclude-source-types": ["scheduler"],
                    }
                ]
            },
            None,
        ),
        # The deprecated field cannot be mixed with the new fields
        (
            {
                "inflexible-device-sensors": ["attributeless power"],
                "inflexible-production": [{"sensor": "production-positive power"}],
            },
            {
                "inflexible-device-sensors": "Must pass either inflexible-device-sensors (deprecated) or inflexible-consumption/inflexible-production."
            },
        ),
        # A sensor may be listed only once across the new fields
        (
            {
                "inflexible-consumption": [{"sensor": "attributeless power"}],
                "inflexible-production": [{"sensor": "attributeless power"}],
            },
            {"inflexible-production": "may only be listed once"},
        ),
        # ... also within a single field
        (
            {
                "inflexible-consumption": [
                    {"sensor": "attributeless power"},
                    {"sensor": "attributeless power"},
                ],
            },
            {"inflexible-consumption": "may only be listed once"},
        ),
        # An explicitly contradicting consumption_is_positive attribute is rejected
        (
            {"inflexible-consumption": [{"sensor": "production-positive power"}]},
            {"inflexible-consumption": "conflicts with the sign convention"},
        ),
        (
            {"inflexible-production": [{"sensor": "consumption-positive power"}]},
            {"inflexible-production": "conflicts with the sign convention"},
        ),
        # The new fields can also be set per commodity context
        (
            {
                "commodities": [
                    {
                        "commodity": "electricity",
                        "inflexible-production": [{"sensor": "attributeless power"}],
                    }
                ]
            },
            None,
        ),
        # ... where mixing with the deprecated field is equally rejected
        (
            {
                "commodities": [
                    {
                        "commodity": "electricity",
                        "inflexible-device-sensors": ["attributeless power"],
                        "inflexible-consumption": [
                            {"sensor": "consumption-positive power"}
                        ],
                    }
                ]
            },
            {
                "commodities.0.inflexible-device-sensors": "Must pass either inflexible-device-sensors"
            },
        ),
    ],
)
def test_flex_context_schema_inflexible_devices(
    db, app, setup_inflexible_sensors, flex_context, fails
):
    """Validation of the inflexible-consumption/inflexible-production fields."""

    def resolve_sensor_names(node):
        """Replace sensor names in the parametrized flex-context with sensor ids."""
        if isinstance(node, dict):
            return {
                key: (
                    setup_inflexible_sensors[value].id
                    if key == "sensor"
                    else resolve_sensor_names(value)
                )
                for key, value in node.items()
            }
        if isinstance(node, list):
            return [
                (
                    setup_inflexible_sensors[item].id
                    if isinstance(item, str) and item in setup_inflexible_sensors
                    else resolve_sensor_names(item)
                )
                for item in node
            ]
        return node

    check_schema_loads_data(
        schema=FlexContextSchema(),
        data=resolve_sensor_names(flex_context),
        fails=fails,
    )


def test_flex_context_schema_inflexible_devices_deserialization(
    db, app, setup_inflexible_sensors
):
    """Entries deserialize to plain Sensors, or SensorReferences when filtered."""
    consumption_sensor = setup_inflexible_sensors["consumption-positive power"]
    plain_sensor = setup_inflexible_sensors["attributeless power"]
    filtered_sensor = setup_inflexible_sensors["production-positive power"]
    data = FlexContextSchema().load(
        {
            "inflexible-consumption": [{"sensor": consumption_sensor.id}],
            "inflexible-production": [
                {"sensor": plain_sensor.id},
                {"sensor": filtered_sensor.id, "source-types": ["forecaster"]},
            ],
        }
    )
    assert data["inflexible_consumption"] == [consumption_sensor]
    assert data["inflexible_production"][0] == plain_sensor
    reference = data["inflexible_production"][1]
    assert isinstance(reference, SensorReference)
    assert reference.sensor == filtered_sensor
    assert reference.source_types == ["forecaster"]


def test_storage_flex_model_inflexible_device_field(
    db, app, setup_dummy_sensors, setup_inflexible_sensors
):
    """A flex-model entry can declare an inflexible device via a single
    inflexible-consumption/production reference. Both signs on one entry, a sensor
    whose explicit sign contradicts the field, and a co-existing schedulable field are
    all rejected."""
    consumption_positive = setup_inflexible_sensors["consumption-positive power"]
    production_positive = setup_inflexible_sensors["production-positive power"]
    attributeless = setup_inflexible_sensors["attributeless power"]

    for schema in (
        StorageFlexModelSchema(
            start=datetime(2026, 6, 1, tzinfo=pytz.UTC), sensor=None
        ),
        DBStorageFlexModelSchema(),
    ):
        # A plain reference deserializes to a Sensor.
        loaded = schema.load({"inflexible-consumption": {"sensor": attributeless.id}})
        assert loaded["inflexible_consumption"] == attributeless

        # A source-filtered reference deserializes to a SensorReference.
        loaded = schema.load(
            {
                "inflexible-production": {
                    "sensor": attributeless.id,
                    "source-types": ["forecaster"],
                }
            }
        )
        assert isinstance(loaded["inflexible_production"], SensorReference)

        # Declaring both signs on one entry is rejected.
        with pytest.raises(ValidationError, match="not both"):
            schema.load(
                {
                    "inflexible-consumption": {"sensor": attributeless.id},
                    "inflexible-production": {"sensor": attributeless.id},
                }
            )

        # A sensor whose explicit consumption_is_positive contradicts the field.
        with pytest.raises(ValidationError, match="conflicts with the sign convention"):
            schema.load({"inflexible-consumption": {"sensor": production_positive.id}})
        with pytest.raises(ValidationError, match="conflicts with the sign convention"):
            schema.load({"inflexible-production": {"sensor": consumption_positive.id}})

        # An inflexible entry must not also carry a schedulable-device field. The check
        # is a whitelist, so it also catches less-obvious device fields (e.g. soc-unit),
        # not just an enumerated blacklist.
        with pytest.raises(ValidationError, match="schedulable-device field"):
            schema.load(
                {
                    "inflexible-consumption": {"sensor": attributeless.id},
                    "power-capacity": "1 MW",
                }
            )

    # soc-unit exists only on StorageFlexModelSchema, and is also rejected.
    with pytest.raises(ValidationError, match="schedulable-device field"):
        StorageFlexModelSchema(
            start=datetime(2026, 6, 1, tzinfo=pytz.UTC), sensor=None
        ).load(
            {
                "inflexible-consumption": {"sensor": attributeless.id},
                "soc-unit": "kWh",
            }
        )


def test_db_flex_context_schema_inflexible_devices(
    db, app, setup_inflexible_sensors, setup_price_sensors
):
    """The DB schema holds all three inflexible-device fields to power/energy units."""
    schema = DBFlexContextSchema()
    price_sensor = setup_price_sensors["consumption-price in SEK/kWh"]
    with pytest.raises(ValidationError, match="must have a power or energy unit"):
        schema.load({"inflexible-consumption": [{"sensor": price_sensor.id}]})
    with pytest.raises(ValidationError, match="must have a power or energy unit"):
        schema.load({"inflexible-device-sensors": [price_sensor.id]})
    # The deprecated field alone remains supported
    schema.load(
        {
            "inflexible-device-sensors": [
                setup_inflexible_sensors["attributeless power"].id
            ]
        }
    )


def test_db_flex_model_accepts_an_internal_commodity(app):
    """A db-stored flex-model accepts a commodity outside electricity and gas.

    Internal commodity nodes carry labels like "steam" or "heat",
    so the set of commodities is open rather than an enumeration.
    Without this, a converter feeding an internal node could be scheduled but not stored.
    """
    loaded = DBStorageFlexModelSchema().load(
        {
            "commodity": "steam",
            "coupling": "chp",
            "coupling-coefficient": 0.5,
            "production-capacity": "10 kW",
        }
    )
    assert loaded["commodity"] == "steam"


@pytest.mark.parametrize("blank", ["", " ", "\t"])
def test_blank_commodity_is_rejected(app, blank):
    """An open commodity set still excludes blank names, on both schemas."""
    with pytest.raises(ValidationError):
        DBStorageFlexModelSchema().load({"commodity": blank})
    with pytest.raises(ValidationError):
        StorageFlexModelSchema(
            start=datetime(2026, 6, 1, tzinfo=pytz.utc), sensor=None
        ).load({"commodity": blank, "power-capacity": "20 kW"})


def test_tutorial_chp_example_validates(app):
    """The CHP example in the multi-commodity tutorial validates as written.

    It is the example a reader copies, so it should load through the schema that stores it,
    and each port's coupling direction should resolve from its single directional capacity.
    """
    from flexmeasures.data.models.planning.devices import (
        _resolve_coupling_coefficient,
    )

    ports = [
        (
            {
                "commodity": "gas",
                "coupling-coefficient": 1.0,
                "consumption-capacity": "20 kW",
            },
            1.0,
        ),
        (
            {
                "commodity": "steam",
                "coupling-coefficient": 0.5,
                "production-capacity": "10 kW",
            },
            -0.5,
        ),
        (
            {
                "commodity": "electricity",
                "coupling-coefficient": 0.3,
                "production-capacity": "6 kW",
            },
            -0.3,
        ),
    ]
    for entry, expected_coefficient in ports:
        loaded = DBStorageFlexModelSchema().load({**entry, "coupling": "chp"})
        assert _resolve_coupling_coefficient(loaded) == pytest.approx(
            expected_coefficient
        )


@pytest.mark.parametrize(
    ["flex_context", "device_softened", "soc_softened", "site_softened"],
    [
        # Nothing given: relax-constraints defaults to True,
        # which softens the SoC and site capacity constraints, but not the device directional capacities.
        ({}, False, True, True),
        # Writing out the default changes nothing:
        # the blanket does not cover device capacities either way.
        ({"relax-constraints": True}, False, True, True),
        # Device capacities are relaxed by naming them.
        ({"relax-capacity-constraints": True}, True, True, True),
        # Explicitly opting out keeps everything hard.
        ({"relax-constraints": False}, False, False, False),
        # Opting out of the blanket while opting into device capacity relaxation.
        (
            {"relax-constraints": False, "relax-capacity-constraints": True},
            True,
            False,
            False,
        ),
    ],
)
def test_device_capacity_relaxation_is_opt_in(
    flex_context, device_softened, soc_softened, site_softened
):
    """The blanket relax-constraints must not soften device directional capacities.

    A directional capacity can state a physical impossibility (a heat pump that cannot produce),
    so making it breachable at a price has to name the thing being softened,
    through relax-capacity-constraints or through the device breach prices themselves.

    Note that passing relax-constraints explicitly behaves the same as leaving it out:
    the field defaults to True, so writing out that default must not change anything.
    """
    loaded = FlexContextSchema().load(flex_context)

    assert (loaded.get("consumption_breach_price") is not None) is device_softened
    assert (loaded.get("production_breach_price") is not None) is device_softened
    assert (loaded.get("soc_minima_breach_price") is not None) is soc_softened
    assert (loaded.get("soc_maxima_breach_price") is not None) is soc_softened
    assert (loaded.get("ems_consumption_breach_price") is not None) is site_softened
    assert (loaded.get("ems_production_breach_price") is not None) is site_softened


def test_explicit_device_breach_price_is_not_overwritten():
    """An explicitly given device breach price survives relax-capacity-constraints.

    ``set_default_breach_prices`` assigns unconditionally,
    so the guard has to keep it from running at all when the caller already priced a breach themselves.
    """
    loaded = FlexContextSchema().load(
        {
            "relax-capacity-constraints": True,
            "consumption-breach-price": "7 EUR/kW",
        }
    )

    assert loaded["consumption_breach_price"] == ur.Quantity("7 EUR/kW")
    # The opposite direction is left alone too:
    # pricing one direction explicitly puts the caller in charge of both, rather than mixing their price with our default.
    assert loaded.get("production_breach_price") is None
