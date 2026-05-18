from flexmeasures.data.schemas.reporting.pandas_reporter import (
    PandasReporterConfigSchema,
    PandasReporterParametersSchema,
)
from flexmeasures.data.schemas.reporting.profit import (
    ProfitOrLossReporterConfigSchema,
    ProfitOrLossReporterParametersSchema,
)
from flexmeasures.data.schemas.reporting import BeliefsSearchConfigSchema
from marshmallow.exceptions import ValidationError

import pytest


@pytest.mark.parametrize(
    "config, is_valid",
    [
        (
            {  # this checks that the final_df_output dataframe is actually generated at some point of the processing pipeline
                "required_input": [{"name": "sensor_1"}],
                "required_output": [{"name": "final_output"}],
                "transformations": [
                    {
                        "df_output": "final_output",
                        "df_input": "sensor_1",
                        "method": "copy",
                    }
                ],
            },
            True,
        ),
        (
            {  # this checks that chaining works, applying the method copy on the previous dataframe
                "required_input": [{"name": "sensor_1"}],
                "required_output": [{"name": "final_output"}],
                "transformations": [
                    {"df_output": "output1", "df_input": "sensor_1", "method": "copy"},
                    {"method": "copy"},
                    {"df_output": "final_output", "method": "copy"},
                ],
            },
            True,
        ),
        (
            {  # this checks that resample cannot be the last method being applied
                "required_input": [{"name": "sensor_1"}, {"name": "sensor_2"}],
                "required_output": [{"name": "final_output"}],
                "transformations": [
                    {"df_output": "output1", "df_input": "sensor_1", "method": "copy"},
                    {"method": "copy"},
                    {"df_output": "final_output", "method": "resample", "args": ["1h"]},
                ],
            },
            False,
        ),
        (
            {  # this checks that resample cannot be the last method being applied
                "required_input": [{"name": "sensor_1"}, {"name": "sensor_2"}],
                "required_output": [{"name": "final_output"}],
                "transformations": [
                    {"df_output": "output1", "df_input": "sensor_1", "method": "copy"},
                    {"method": "copy"},
                    {"df_output": "final_output", "method": "resample", "args": ["1h"]},
                    {"method": "asfreq"},
                ],
            },
            True,
        ),
    ],
)
def test_pandas_reporter_config_schema(config, is_valid, db, app, setup_dummy_sensors):

    schema = PandasReporterConfigSchema()

    if is_valid:
        schema.load(config)
    else:
        with pytest.raises(ValidationError):
            schema.load(config)


@pytest.mark.parametrize(
    "parameters, is_valid",
    [
        (
            {
                "input": [
                    {
                        "name": "sensor_1_df",
                        "sensor": 1,
                    }  # we're describing how the named variables should be constructed, by defining search filters on the sensor data, rather than on the sensor
                ],
                "output": [
                    {"name": "df2", "sensor": 2}
                ],  # sensor to save the output to
                "start": "2023-06-06T00:00:00+02:00",
                "end": "2023-06-06T00:00:00+02:00",
            },
            True,
        ),
        (  # missing start and end
            {
                "input": [{"name": "sensor_1_df", "sensor": 1}],
                "output": [{"name": "df2", "sensor": 2}],
            },
            False,
        ),
        (
            {
                "input": [
                    {
                        "name": "sensor_1_df",
                        "sensor": 1,
                        "event_starts_after": "2023-06-07T00:00:00+02:00",
                        "event_ends_before": "2023-06-07T00:00:00+02:00",
                    }
                ],
                "output": [
                    {"name": "df2", "sensor": 2}
                ],  # sensor to save the output to
            },
            True,
        ),
    ],
)
def test_pandas_reporter_parameters_schema(
    parameters, is_valid, db, app, setup_dummy_sensors
):

    schema = PandasReporterParametersSchema()

    if is_valid:
        schema.load(parameters)
    else:
        with pytest.raises(ValidationError):
            schema.load(parameters)


@pytest.mark.parametrize(
    "config, is_valid",
    [
        (  # missing start and end
            {
                "consumption_price_sensor": 2,
                "production_price_sensor": 2,
            },
            True,
        ),
        (
            {
                "consumption_price_sensor": 2,
            },
            True,
        ),
        (
            {
                "production_price_sensor": 2,
            },
            True,
        ),
        (
            {},
            False,
        ),
    ],
)
def test_profit_reporter_config_schema(config, is_valid, db, app, setup_dummy_sensors):
    schema = ProfitOrLossReporterConfigSchema()

    if is_valid:
        schema.load(config)
    else:
        with pytest.raises(ValidationError):
            schema.load(config)


start = "2023-01-01T00:00:00+01:00"
end = "2023-01-02T00:00:00+01:00"


@pytest.mark.parametrize(
    "parameters, is_valid",
    [
        (
            {
                "input": [{"sensor": 1}],  # unit: MWh
                "output": [{"sensor": 3}],  # unit : EUR
                "start": start,
                "end": end,
            },
            True,
        ),
        (
            {
                "input": [{"sensor": 4}],  # unit: MW
                "output": [{"sensor": 3}],  # unit : EUR
                "start": start,
                "end": end,
            },
            True,
        ),
        (  # wrong output unit
            {
                "input": [{"sensor": 4}],  # unit: MW
                "output": [{"sensor": 4}],  # unit : MW
                "start": start,
                "end": end,
            },
            False,
        ),
        (  # wrong input unit
            {
                "input": [{"sensor": 3}],  # unit: EUR
                "output": [{"sensor": 3}],  # unit : EUR
                "start": start,
                "end": end,
            },
            False,
        ),
    ],
)
def test_profit_reporter_parameters_schema(
    parameters, is_valid, db, app, setup_dummy_sensors
):
    schema = ProfitOrLossReporterParametersSchema()

    if is_valid:
        schema.load(parameters)
    else:
        with pytest.raises(ValidationError):
            schema.load(parameters)


@pytest.mark.parametrize(
    "make_config, is_valid",
    [
        (
            lambda p, s: {"source_account_ids": p},
            True,
        ),
        (
            lambda p, s: {"source_account_ids": [p]},
            True,
        ),
        (
            lambda p, s: {"source_account_ids": [p, s]},
            True,
        ),
        (
            lambda p, s: {"source_account_ids": []},
            False,
        ),
        (
            lambda p, s: {"source_account_ids": "not-a-list"},
            False,
        ),
        (
            lambda p, s: {"source_account_ids": ["a", "b"]},
            False,
        ),
    ],
    ids=[
        "single-int",
        "single-item-list",
        "multi-item-list",
        "empty-list",
        "string",
        "list-of-strings",
    ],
)
def test_beliefs_search_config_schema_source_account_ids(
    make_config, is_valid, db, app, setup_accounts
):
    """Check that BeliefsSearchConfigSchema accepts source_account_ids as a single int or list of ints,
    rejects empty lists and non-integer values, and validates accounts exist in the DB.
    """
    prosumer_id = setup_accounts["Prosumer"].id
    supplier_id = setup_accounts["Supplier"].id
    config = make_config(prosumer_id, supplier_id)
    schema = BeliefsSearchConfigSchema()
    if is_valid:
        result = schema.load(config)
        assert isinstance(result["source_account_ids"], list)
        assert len(result["source_account_ids"]) >= 1
    else:
        with pytest.raises(ValidationError):
            schema.load(config)
