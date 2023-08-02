from flexmeasures.data.schemas.reporting.pandas_reporter import (
    PandasReporterConfigSchema,
    PandasReporterInputSchema,
)
from marshmallow.exceptions import ValidationError

import pytest


@pytest.mark.parametrize(
    "config, is_valid",
    [
        (
            {  # this checks that the final_df_output dataframe is actually generated at some point of the processing pipeline
                "input_variables": ["sensor_1"],
                "transformations": [
                    {
                        "df_output": "final_output",
                        "df_input": "sensor_1",
                        "method": "copy",
                    }
                ],
                "final_df_output": "final_output",
            },
            True,
        ),
        (
            {  # this checks that chaining works, applying the method copy on the previous dataframe
                "input_variables": ["sensor_1"],
                "transformations": [
                    {"df_output": "output1", "df_input": "sensor_1", "method": "copy"},
                    {"method": "copy"},
                    {"df_output": "final_output", "method": "copy"},
                ],
                "final_df_output": "final_output",
            },
            True,
        ),
        (
            {  # this checks that resample cannot be the last method being applied
                "input_variables": ["sensor_1", "sensor_2"],
                "transformations": [
                    {"df_output": "output1", "df_input": "sensor_1", "method": "copy"},
                    {"method": "copy"},
                    {"df_output": "final_output", "method": "resample", "args": ["1h"]},
                ],
                "final_df_output": "final_output",
            },
            False,
        ),
        (
            {  # this checks that resample cannot be the last method being applied
                "input_variables": ["sensor_1", "sensor_2"],
                "transformations": [
                    {"df_output": "output1", "df_input": "sensor_1", "method": "copy"},
                    {"method": "copy"},
                    {"df_output": "final_output", "method": "resample", "args": ["1h"]},
                    {"method": "sum"},
                ],
                "final_df_output": "final_output",
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
    "input, is_valid",
    [
        (
            {
                "sensor": 2,  # sensor to save the output to
                "input_variables": {  # we're describing how the named variables should be constructed, by defining search filters on the sensor data, rather than on the sensor
                    "sensor_1_df": {
                        "sensor": 1
                    },  # alias, i.e. variable name of the DataFrame containing the input data
                },
                "start": "2023-06-06T00:00:00+02:00",
                "end": "2023-06-06T00:00:00+02:00",
            },
            True,
        ),
        (
            {
                "input_variables": {
                    "sensor_1_df": {
                        "sensor": 1
                    }  # alias, i.e. variable name of the DataFrame containing the input data
                },
            },
            False,
        ),
        (
            {
                "sensor": 2,  # sensor to save the output to
                "input_variables": {
                    "sensor_1_df": {  # alias, i.e. variable name of the DataFrame containing the input data
                        "sensor": 1,
                        "event_starts_after": "2023-06-07T00:00:00+02:00",
                        "event_ends_before": "2023-06-07T00:00:00+02:00",
                    }
                },
            },
            True,
        ),
    ],
)
def test_pandas_reporter_input_schema(input, is_valid, db, app, setup_dummy_sensors):

    schema = PandasReporterInputSchema()

    if is_valid:
        schema.load(input)
    else:
        with pytest.raises(ValidationError):
            schema.load(input)
