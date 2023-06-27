from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType

from flexmeasures.data.schemas.reporting.pandas_reporter import (
    PandasReporterConfigSchema,
    PandasReporterInputConfigSchema,
)
from marshmallow.exceptions import ValidationError

import pytest


@pytest.fixture(scope="module")
def setup_dummy_sensors(db, app):

    dummy_asset_type = GenericAssetType(name="DummyGenericAssetType")
    db.session.add(dummy_asset_type)

    dummy_asset = GenericAsset(
        name="DummyGenericAsset", generic_asset_type=dummy_asset_type
    )
    db.session.add(dummy_asset)

    sensor1 = Sensor("sensor 1", generic_asset=dummy_asset)
    db.session.add(sensor1)
    sensor2 = Sensor("sensor 2", generic_asset=dummy_asset)
    db.session.add(sensor2)

    db.session.commit()

    yield sensor1, sensor2

    db.session.delete(sensor1)
    db.session.delete(sensor2)

    db.session.commit()


@pytest.mark.parametrize(
    "config, is_valid",
    [
        (
            {  # this checks that the final_df_output dataframe is actually generated at some point of the processing pipeline
                "sensor": 1,
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
                "sensor": 1,
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
                "sensor": 1,
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
                "sensor": 1,
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
    "inputs, is_valid",
    [
        (
            {
                "input_sensors": {"sensor_1": {"sensor": 1}},
                "start": "2023-06-06T00:00:00+02:00",
                "end": "2023-06-06T00:00:00+02:00",
            },
            True,
        ),
        (
            {
                "input_sensors": {"sensor_1": {"sensor": 1}},
            },
            False,
        ),
        (
            {
                "input_sensors": {
                    "sensor_1": {
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
def test_pandas_reporter_inputs_schema(inputs, is_valid, db, app, setup_dummy_sensors):

    schema = PandasReporterInputConfigSchema()

    if is_valid:
        schema.load(inputs)
    else:
        with pytest.raises(ValidationError):
            schema.load(inputs)
