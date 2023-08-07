from flexmeasures.data.schemas.reporting.pandas_reporter import (
    PandasReporterConfigSchema,
    PandasReporterParametersSchema,
)
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
                    {"method": "sum"},
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
