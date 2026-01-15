import pytest

import pandas as pd

from flexmeasures.data.schemas.forecasting.pipeline import ForecasterParametersSchema


@pytest.mark.parametrize(
    ["timing_input", "expected_timing_output"],
    [
        # Test defaults when no timing parameters are given
        (
            # {},
            # {
            #     # todo: include every timing parameter in expected_timing_output
            # },
        ),
        # Test defaults when only an end date is given
        (
            {"end_date": "2023-03-27T00:00:00+02:00"},
            {
                "end_date": pd.Timestamp("2023-03-27T00:00:00+02:00", tz="Asia/Seoul"),
                "predict_start": pd.Timestamp.now(tz="Asia/Seoul").floor(
                    "1H"
                ),  # 1st sensor in setup_dummy_sensors is hourly
                "max_forecast_horizon": pd.Timedelta("PT48H"),
                # todo: include every timing parameter in expected_timing_output
            },
        ),
    ],
)
def test_timing_parameters_of_forecaster_parameters_schema(
    setup_dummy_sensors, timing_input, expected_timing_output
):
    data = ForecasterParametersSchema().load(
        {
            "sensor": 1,
            **timing_input,
        }
    )
    print(data)
    for k, v in expected_timing_output.items():
        assert data[k] == v
