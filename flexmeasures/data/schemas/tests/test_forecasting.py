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
                ).floor("1h"),
                # default training period 30 days. before predict_start
                "start_date": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01", tz="Europe/Amsterdam"
                ).floor("1h")
                - pd.Timedelta(days=30),
                # default prediction period 48 hours after predict_start
                "end_date": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01", tz="Europe/Amsterdam"
                ).floor("1h")
                + pd.Timedelta(hours=48),
                # these are set by the schema defaults
                "predict_period_in_hours": 48,
                "max_forecast_horizon": pd.Timedelta(days=2),
                "train_period_in_hours": 720,
                "max_training_period": pd.Timedelta(days=365),
                "forecast_frequency": pd.Timedelta(days=2),
                # server now
                "save_belief_time": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01",
                    tz="Europe/Amsterdam",
                ),
            },
        ),
        # Test defaults when only an end date is given
        (
            {"end_date": "2025-01-20T12:00:00+01:00"},
            {
                "predict_start": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01",
                    tz="Europe/Amsterdam",
                ).floor("1h"),
                "start_date": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01",
                    tz="Europe/Amsterdam",
                ).floor("1h")
                - pd.Timedelta(
                    days=30
                ),  # default training period 30 days before predict_start
                "end_date": pd.Timestamp(
                    "2025-01-20T12:00:00+01",
                    tz="Europe/Amsterdam",
                ),
                "train_period_in_hours": 720,  # from start_date to predict_start
                "predict_period_in_hours": 120,  # from predict_start to end_date
                "forecast_frequency": pd.Timedelta(days=5), # duration between predict_start and end_date
                "max_forecast_horizon": pd.Timedelta(days=5), # duration between predict_start and end_date
                # default values
                "max_training_period": pd.Timedelta(days=365),
                # server now
                "save_belief_time": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01",
                    tz="Europe/Amsterdam",
                ),
            },
        ),
        # Test when both start and end dates are given
        (
            {
                "start_date": "2024-12-20T00:00:00+01:00",
                "end_date": "2025-01-20T00:00:00+01:00",
            },
            {
                "start_date": pd.Timestamp(
                    "2024-12-20T00:00:00+01", tz="Europe/Amsterdam"
                ),
                "end_date": pd.Timestamp(
                    "2025-01-20T00:00:00+01", tz="Europe/Amsterdam"
                ),
                "predict_start": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01",
                    tz="Europe/Amsterdam",
                ).floor("1h"),
                "predict_period_in_hours": 108,  # hours from predict_start to end_date
                "train_period_in_hours": 636,  # hours between start_date and predict_start
                "max_forecast_horizon": pd.Timedelta(days=4) + pd.Timedelta(hours=12), # duration between predict_start and end_date
                "forecast_frequency": pd.Timedelta(days=4) + pd.Timedelta(hours=12), # duration between predict_start and end_date
                # default values
                "max_training_period": pd.Timedelta(days=365),
                # server now
                "save_belief_time": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01",
                    tz="Europe/Amsterdam",
                ),
            },
        ),
        # Test when only end date is given with a training period
        # We expect the start date to be computed with respect to now. (training period before now (floored)).
        (
            {
                "end_date": "2025-01-20T12:00:00+01:00",
                "train_period": "P3D",
            },
            {
                "end_date": pd.Timestamp(
                    "2025-01-20T12:00:00+01", tz="Europe/Amsterdam"
                ),
                "predict_start": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01",
                    tz="Europe/Amsterdam",
                ).floor("1h"),
                "start_date": pd.Timestamp(
                    "2025-01-15T12:00:00+01", tz="Europe/Amsterdam"
                )
                - pd.Timedelta(days=3),
                "train_period_in_hours": 72,  # from start_date to predict_start
                "predict_period_in_hours": 120,  # from predict_start to end_date
                "max_forecast_horizon": pd.Timedelta(days=5), # duration between predict_start and end_date
                "forecast_frequency": pd.Timedelta(days=5), # duration between predict_start and end_date
                # default values
                "max_training_period": pd.Timedelta(days=365),
                # server now
                "save_belief_time": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01",
                    tz="Europe/Amsterdam",
                ),
            },
        ),
        # Test when only start date is given with a training period
        # We expect the predict start to be computed with respect to the start date (training period after start date).
        (
            {
                "start_date": "2024-12-25T00:00:00+01:00",
                "train_period": "P3D",
            },
            {
                "start_date": pd.Timestamp(
                    "2024-12-25T00:00:00+01", tz="Europe/Amsterdam"
                ),
                "predict_start": pd.Timestamp(
                    "2024-12-25T00:00:00+01", tz="Europe/Amsterdam"
                )
                + pd.Timedelta(days=3),
                "end_date": pd.Timestamp(
                    "2024-12-28T00:00:00+01", tz="Europe/Amsterdam"
                )
                + pd.Timedelta(days=2),
                "train_period_in_hours": 72,
                "max_forecast_horizon": pd.Timedelta(days=2), # duration between predict_start and end_date
                "forecast_frequency": pd.Timedelta(days=2), # duration between predict_start and end_date
                # default values
                "predict_period_in_hours": 48,
                "max_training_period": pd.Timedelta(days=365),
                # the belief time of the forecasts will be calculated from start_predict_date and max_forecast_horizon and forecast_frequency
                "save_belief_time": None,
            },
        ),
        # Test when only start date is given with a retrain frequency (prediction period)
        (
            {
                "start_date": "2024-12-25T00:00:00+01:00",
                "retrain_frequency": "P3D",
            },
            {
                "start_date": pd.Timestamp(
                    "2024-12-25T00:00:00+01", tz="Europe/Amsterdam"
                ),
                "predict_start": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01",
                    tz="Europe/Amsterdam",
                ).floor("1h"),
                "end_date": pd.Timestamp(
                    "2025-01-15T12:00:00+01", tz="Europe/Amsterdam"
                )
                + pd.Timedelta(days=3),
                "predict_period_in_hours": 72,
                "train_period_in_hours": 516,  # from start_date to predict_start
                "max_forecast_horizon": pd.Timedelta(days=3),  # duration between predict_start and end_date
                "forecast_frequency": pd.Timedelta(days=3),  # duration between predict_start and end_date                
                # default values
                "max_training_period": pd.Timedelta(days=365),
                # server now
                "save_belief_time": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01",
                    tz="Europe/Amsterdam",
                ),
            },
        ),
        # Test when only start date is given with both training period and retrain frequency
        (
            {
                "start_date": "2024-12-01T00:00:00+01:00",
                "train_period": "P20D",
                "retrain_frequency": "P3D",
            },
            {
                "start_date": pd.Timestamp(
                    "2024-12-01T00:00:00+01", tz="Europe/Amsterdam"
                ),
                "predict_start": pd.Timestamp(
                    "2024-12-01T00:00:00+01", tz="Europe/Amsterdam"
                )
                + pd.Timedelta(days=20),
                "end_date": pd.Timestamp(
                    "2024-12-01T00:00:00+01", tz="Europe/Amsterdam"
                )
                + pd.Timedelta(days=23),
                "train_period_in_hours": 480,
                "predict_period_in_hours": 72,
                "max_forecast_horizon": pd.Timedelta(days=3),  # predict period duration 
                "forecast_frequency": pd.Timedelta(days=3),  # predict period duration
                # default values
                "max_training_period": pd.Timedelta(days=365),
                # the belief time of the forecasts will be calculated from start_predict_date and max_forecast_horizon and forecast_frequency
                "save_belief_time": None,
            },
        ),
        # Test when only end date is given with a prediction period: we expect the train start and predict start to both be computed with respect to the end date.
        (
            {
                "end_date": "2025-01-20T12:00:00+01:00",
                "retrain_frequency": "P3D",
            },
            {
                "end_date": pd.Timestamp(
                    "2025-01-20T12:00:00+01", tz="Europe/Amsterdam"
                ),
                "predict_start": pd.Timestamp(
                    "2025-01-15T12:00:00+01", tz="Europe/Amsterdam"
                ),
                "start_date": pd.Timestamp(
                    "2025-01-15T12:00:00+01", tz="Europe/Amsterdam"
                )
                - pd.Timedelta(days=30),
                "predict_period_in_hours": 72,
                "train_period_in_hours": 720,
                "max_forecast_horizon": pd.Timedelta(days=3), # duration between predict_start and end_date (retrain frequency)
                "forecast_frequency": pd.Timedelta(days=3), # duration between predict_start and end_date (retrain frequency)
                # default values
                "max_training_period": pd.Timedelta(days=365),
                # server now
                "save_belief_time": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01",
                    tz="Europe/Amsterdam",
                ),
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
