import pytest

import pandas as pd

from flexmeasures.data.schemas.forecasting.pipeline import ForecasterParametersSchema


@pytest.mark.parametrize(
    ["timing_input", "expected_timing_output"],
    [
        # Test defaults when no timing parameters are given
        (
            {},
            {
                "predict_start": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01", tz="Europe/Amsterdam"
                ).floor("1H"),
                # default training period 30 days. before predict_start
                "start_date": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01", tz="Europe/Amsterdam"
                ).floor("1H")
                - pd.Timedelta(days=30), 
                # default prediction period 48 hours after predict_start
                "end_date": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01", tz="Europe/Amsterdam"
                ).floor("1H")
                + pd.Timedelta(hours=48), #
                # these are set by the schema defaults
                "predict_period_in_hours": 48,
                "max_forecast_horizon": pd.Timedelta(hours=48),
                "train_period_in_hours": 720,
                "max_training_period": pd.Timedelta(days=365),
                "forecast_frequency": pd.Timedelta(hours=1),
            },
        ),
        # Test defaults when only an end date is given
        (
            {"end_date": "2025-03-27T00:00:00+02:00"},
            {
                "end_date": pd.Timestamp("2025-03-27T00:00:00+02:00", tz="Asia/Seoul"),
                "predict_start": pd.Timestamp("2025-01-15T12:23:58.387422+01").floor(
                    "1H"
                ),  # 1st sensor in setup_dummy_sensors is hourly
                "max_forecast_horizon": pd.Timedelta("PT48H"),
                # todo: include every timing parameter in expected_timing_output
            },
        ),
    ],
)
def test_timing_parameters_of_forecaster_parameters_schema(
    setup_dummy_sensors, freeze_server_now, timing_input, expected_timing_output
):
    freeze_server_now(
        pd.Timestamp("2025-01-15T12:23:58.387422+01", tz="Europe/Amsterdam")
    )

    data = ForecasterParametersSchema().load(
        {
            "sensor": 1,
            **timing_input,
        }
    )

    for k, v in expected_timing_output.items():
        assert data[k] == v
