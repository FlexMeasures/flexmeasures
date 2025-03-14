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
)
from flexmeasures.data.schemas.sensors import TimedEventSchema


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
    sensor1, _ = setup_dummy_sensors

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
    sensor1, _ = setup_dummy_sensors

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

    sensor1, _ = setup_dummy_sensors

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
            {"site-peak-production-price": "Prices must share the same monetary unit."},
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
    ],
)
def test_flex_context_schema(db, app, setup_site_capacity_sensor, flex_context, fails):
    schema = FlexContextSchema()

    # Replace sensor name with sensor ID
    for field_name, field_value in flex_context.items():
        if isinstance(field_value, dict):
            flex_context[field_name]["sensor"] = setup_site_capacity_sensor[
                field_value["sensor"]
            ].id

    if fails:
        with pytest.raises(ValidationError) as e_info:
            schema.load(flex_context)
        print(e_info.value.messages)
        for field_name, expected_message in fails.items():
            assert field_name in e_info.value.messages
            # Check all messages for the given field for the expected message
            assert any(
                [
                    expected_message in message
                    for message in e_info.value.messages[field_name]
                ]
            )
    else:
        schema.load(flex_context)


# test DBFlexContextSchema
@pytest.mark.parametrize(
    ["flex_context", "fails"],
    [
        (
            {"consumption-price": "13000 kW"},
            {
                "consumption_price": "Fixed prices are not currently supported for consumption-price in flex-context fields in the DB.",
            },
        ),
        (
            {"production-price": {"sensor": "site-power-capacity"}},
            {"production_price": "Price field 'production_price' must be a price unit"},
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
                "ems_consumption_breach_price": "Price field 'ems_consumption_breach_price' must be a price unit."
            },
        ),
        (
            {"site-consumption-breach-price": "450 EUR/MW"},
            False,
        ),
        (
            {"site-production-breach-price": "550 KRW/MWh"},
            {
                "ems_production_breach_price": "Price field 'ems_production_breach_price' must be a price unit."
            },
        ),
        (
            {"site-production-breach-price": "3500 NGN/MW"},
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
            {"site-peak-production-price": "4500 NGN/MWh"},
            {
                "ems_peak_production_price": "Price field 'ems_peak_production_price' must be a price unit."
            },
        ),
        (
            {"site-peak-consumption-price": "700 JPY/MW"},
            False,
        ),
    ],
)
def test_db_flex_context_schema(
    db, app, setup_site_capacity_sensor, flex_context, fails
):
    schema = DBFlexContextSchema()

    # Replace sensor name with sensor ID
    for field_name, field_value in flex_context.items():
        if isinstance(field_value, dict):
            flex_context[field_name]["sensor"] = setup_site_capacity_sensor[
                field_value["sensor"]
            ].id

    if fails:
        with pytest.raises(ValidationError) as e_info:
            print("flex_context", flex_context)
            schema.load(flex_context)
        print(e_info.value.messages)
        for field_name, expected_message in fails.items():
            assert field_name in e_info.value.messages
            # Check all messages for the given field for the expected message
            assert any(
                [
                    expected_message in message
                    for message in e_info.value.messages[field_name]
                ]
            )
    else:
        schema.load(flex_context)
