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
                "predict-start": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01", tz="Europe/Amsterdam"
                ).floor("1h"),
                # default training period 30 days. before predict-start
                "start-date": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01", tz="Europe/Amsterdam"
                ).floor("1h")
                - pd.Timedelta(days=30),
                # default prediction period 48 hours after predict-start
                "end-date": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01", tz="Europe/Amsterdam"
                ).floor("1h")
                + pd.Timedelta(hours=48),
                # these are set by the schema defaults
                "predict-period-in-hours": 48,
                "max-forecast-horizon": pd.Timedelta(hours=48),
                "train-period-in-hours": 720,
                "max-training-period": pd.Timedelta(days=365),
                "forecast-frequency": pd.Timedelta(hours=1),
                # server now
                "save-belief-time": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01",
                    tz="Europe/Amsterdam",
                ),
            },
        ),
        # Test defaults when only an end date is given
        (
            {"end-date": "2025-01-20T12:00:00+01:00"},
            {
                "predict-start": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01",
                    tz="Europe/Amsterdam",
                ).floor("1h"),
                "start-date": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01",
                    tz="Europe/Amsterdam",
                ).floor("1h")
                - pd.Timedelta(
                    days=30
                ),  # default training period 30 days before predict-start
                "end-date": pd.Timestamp(
                    "2025-01-20T12:00:00+01",
                    tz="Europe/Amsterdam",
                ),
                "train-period-in-hours": 720,  # from start-date to predict-start
                "predict-period-in-hours": 120,  # from predict-start to end-date
                # default values
                "max-forecast-horizon": pd.Timedelta(hours=48),
                "max-training-period": pd.Timedelta(days=365),
                "forecast-frequency": pd.Timedelta(hours=1),
                # server now
                "save-belief-time": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01",
                    tz="Europe/Amsterdam",
                ),
            },
        ),
        # Test when both start and end dates are given
        (
            {
                "start-date": "2024-12-20T00:00:00+01:00",
                "end-date": "2025-01-20T00:00:00+01:00",
            },
            {
                "start-date": pd.Timestamp(
                    "2024-12-20T00:00:00+01", tz="Europe/Amsterdam"
                ),
                "end-date": pd.Timestamp(
                    "2025-01-20T00:00:00+01", tz="Europe/Amsterdam"
                ),
                "predict-start": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01",
                    tz="Europe/Amsterdam",
                ).floor("1h"),
                "predict-period-in-hours": 108,  # hours from predict-start to end-date
                "train-period-in-hours": 636,  # hours between start-date and predict-start
                # default values
                "max-forecast-horizon": pd.Timedelta(hours=48),
                "max-training-period": pd.Timedelta(days=365),
                "forecast-frequency": pd.Timedelta(hours=1),
                # server now
                "save-belief-time": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01",
                    tz="Europe/Amsterdam",
                ),
            },
        ),
        # Test when only end date is given with a training period
        # We expect the start date to be computed with respect to now. (training period before now (floored)).
        (
            {
                "end-date": "2025-01-20T12:00:00+01:00",
                "train-period": "P3D",
            },
            {
                "end-date": pd.Timestamp(
                    "2025-01-20T12:00:00+01", tz="Europe/Amsterdam"
                ),
                "predict-start": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01",
                    tz="Europe/Amsterdam",
                ).floor("1h"),
                "start-date": pd.Timestamp(
                    "2025-01-15T12:00:00+01", tz="Europe/Amsterdam"
                )
                - pd.Timedelta(days=3),
                "train-period-in-hours": 72,  # from start-date to predict-start
                "predict-period-in-hours": 120,  # from predict-start to end-date
                # default values
                "max-forecast-horizon": pd.Timedelta(hours=48),
                "max-training-period": pd.Timedelta(days=365),
                "forecast-frequency": pd.Timedelta(hours=1),
                # server now
                "save-belief-time": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01",
                    tz="Europe/Amsterdam",
                ),
            },
        ),
        # Test when only start date is given with a training period
        # We expect the predict start to be computed with respect to the start date (training period after start date).
        (
            {
                "start-date": "2024-12-25T00:00:00+01:00",
                "train-period": "P3D",
            },
            {
                "start-date": pd.Timestamp(
                    "2024-12-25T00:00:00+01", tz="Europe/Amsterdam"
                ),
                "predict-start": pd.Timestamp(
                    "2024-12-25T00:00:00+01", tz="Europe/Amsterdam"
                )
                + pd.Timedelta(days=3),
                "end-date": pd.Timestamp(
                    "2024-12-28T00:00:00+01", tz="Europe/Amsterdam"
                )
                + pd.Timedelta(days=2),
                "train-period-in-hours": 72,
                # default values
                "predict-period-in-hours": 48,
                "max-forecast-horizon": pd.Timedelta(hours=48),
                "max-training-period": pd.Timedelta(days=365),
                "forecast-frequency": pd.Timedelta(hours=1),
                # the belief time of the forecasts will be calculated from start-predict-date and max-forecast-horizon and forecast-frequency
                "save-belief-time": None,
            },
        ),
        # Test when only start date is given with a retrain frequency (prediction period)
        (
            {
                "start-date": "2024-12-25T00:00:00+01:00",
                "retrain-frequency": "P3D",
            },
            {
                "start-date": pd.Timestamp(
                    "2024-12-25T00:00:00+01", tz="Europe/Amsterdam"
                ),
                "predict-start": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01",
                    tz="Europe/Amsterdam",
                ).floor("1h"),
                "end-date": pd.Timestamp(
                    "2025-01-15T12:00:00+01", tz="Europe/Amsterdam"
                )
                + pd.Timedelta(days=3),
                "predict-period-in-hours": 72,
                "train-period-in-hours": 516,  # from start-date to predict-start
                # default values
                "max-forecast-horizon": pd.Timedelta(hours=48),
                "max-training-period": pd.Timedelta(days=365),
                "forecast-frequency": pd.Timedelta(hours=1),
                # server now
                "save-belief-time": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01",
                    tz="Europe/Amsterdam",
                ),
            },
        ),
        # Test when only start date is given with both training period and retrain frequency
        (
            {
                "start-date": "2024-12-01T00:00:00+01:00",
                "train-period": "P20D",
                "retrain-frequency": "P3D",
            },
            {
                "start-date": pd.Timestamp(
                    "2024-12-01T00:00:00+01", tz="Europe/Amsterdam"
                ),
                "predict-start": pd.Timestamp(
                    "2024-12-01T00:00:00+01", tz="Europe/Amsterdam"
                )
                + pd.Timedelta(days=20),
                "end-date": pd.Timestamp(
                    "2024-12-01T00:00:00+01", tz="Europe/Amsterdam"
                )
                + pd.Timedelta(days=23),
                "train-period-in-hours": 480,
                "predict-period-in-hours": 72,
                # default values
                "max-forecast-horizon": pd.Timedelta(hours=48),
                "max-training-period": pd.Timedelta(days=365),
                "forecast-frequency": pd.Timedelta(hours=1),
                # the belief time of the forecasts will be calculated from start-predict-date and max-forecast-horizon and forecast-frequency
                "save-belief-time": None,
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
