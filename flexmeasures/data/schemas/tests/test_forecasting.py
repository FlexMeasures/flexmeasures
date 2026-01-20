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
            {"end_date": "2025-01-20T12:00:00+01:00"},
            {
                "predict_start": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01",
                    tz="Europe/Amsterdam",
                ).floor("1H"),

                "start_date": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01",
                    tz="Europe/Amsterdam",
                ).floor("1H")
                - pd.Timedelta(days=30),  # default training period 30 days before predict_start

                "end_date": pd.Timestamp(
                    "2025-01-20T12:00:00+01",
                    tz="Europe/Amsterdam",
                ),
                "train_period_in_hours": 720,  # from start_date to predict_start
                "predict_period_in_hours": 120,   # from predict_start to end_date
                # default values
                "max_forecast_horizon": pd.Timedelta(hours=48),
                "max_training_period": pd.Timedelta(days=365),
                "forecast_frequency": pd.Timedelta(hours=1),
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
