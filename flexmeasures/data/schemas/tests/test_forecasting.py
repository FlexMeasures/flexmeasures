import pytest

import pandas as pd

from flexmeasures.data.schemas.forecasting.pipeline import ForecasterParametersSchema
from flexmeasures.data.schemas.utils import kebab_to_snake


@pytest.mark.parametrize(
    ["timing_input", "expected_timing_output"],
    [
        # todo: move this into the schema docstring
        # Timing parameter defaults
        # - predict-period defaults to minimum of (FM planning horizon and max-forecast-horizon)
        # - max-forecast-horizon defaults to the predict-period
        # - forecast-frequency defaults to minimum of (FM planning horizon, predict-period, max-forecast-horizon)
        # - retraining-frequency defaults to  maximum of (FM planning horizon and forecast-frequency) so at this point we need forecast-frequency calculated
        # Timing parameter constraints
        # - max-forecast-horizon <= predict-period, raise validation error if not respected
        # - if retrain_freq <= forecast-frequency, enforce retrain_freq = forecast-frequency don't crash
        #
        # Case 0: no timing parameters are given
        #
        # User expects to get forecasts for the default FM planning horizon from a single viewpoint (server now, floored to the hour).
        # Specifically, we expect:
        #    - predict-period = FM planning horizon
        #    - max-forecast-horizon = FM planning horizon
        #    - forecast-frequency = FM planning horizon
        #    - (config) retraining-frequency = FM planning horizon
        #    - 1 cycle, 1 belief time
        #    - training-period = 30 days
        (
            {},
            {
                "predict-start": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01", tz="Europe/Amsterdam"
                ).floor("1h"),
                # default training period 30 days before predict start
                "start-date": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01", tz="Europe/Amsterdam"
                ).floor("1h")
                - pd.Timedelta(days=30),
                # default prediction period 48 hours after predict start
                "end-date": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01", tz="Europe/Amsterdam"
                ).floor("1h")
                + pd.Timedelta(hours=48),
                # these are set by the schema defaults
                "predict-period-in-hours": 48,
                "max-forecast-horizon": pd.Timedelta(days=2),
                "train-period-in-hours": 720,
                "max-training-period": pd.Timedelta(days=365),
                "forecast-frequency": pd.Timedelta(days=2),
                # server now
                "save-belief-time": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01",
                    tz="Europe/Amsterdam",
                ),
                "n_cycles": 1,
            },
        ),
        # Case 1: predict-period = 12 hours
        #
        # User expects to get forecasts for the next 12 hours from a single viewpoint.
        # Specifically, we expect:
        #    - max-forecast-horizon = predict-period = 12 hours
        #    - forecast-frequency = predict-period = 12 hours
        #    - (config) retraining-frequency = FM planning horizon
        #    - 1 cycle, 1 belief time
        #    - training-period = 30 days
        (
            {"duration": "PT12H"},
            {
                "predict_start": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01", tz="Europe/Amsterdam"
                ).floor("1h"),
                "start_date": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01", tz="Europe/Amsterdam"
                ).floor("1h")
                - pd.Timedelta(days=30),
                "train_period_in_hours": 720,
                "predict_period_in_hours": 12,
                "max_forecast_horizon": pd.Timedelta(hours=12),
                "forecast_frequency": pd.Timedelta(hours=12),
                "end_date": pd.Timestamp(
                    "2025-01-15T12:00:00+01", tz="Europe/Amsterdam"
                )
                + pd.Timedelta(hours=12),
                "max_training_period": pd.Timedelta(days=365),
                "save_belief_time": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01", tz="Europe/Amsterdam"
                ),
                "n_cycles": 1,
            },
        ),
        # Case 2: max-forecast-horizon = 12 hours
        #
        # User expects to get forecasts for the next 12 hours from a single viewpoint (same as case 1).
        # Specifically, we expect:
        #    - predict-period = 12 hours
        #    - forecast-frequency = max-forecast-horizon = 12 hours
        #    - retraining-period = FM planning horizon
        #    - 1 cycle, 1 belief time
        # (
        #     {"max-forecast-horizon": "PT12H"},
        #     {
        #         "predict_start": pd.Timestamp(
        #             "2025-01-15T12:23:58.387422+01", tz="Europe/Amsterdam"
        #         ).floor("1h"),
        #         "start_date": pd.Timestamp(
        #             "2025-01-15T12:23:58.387422+01", tz="Europe/Amsterdam"
        #         ).floor("1h")
        #         - pd.Timedelta(days=30),
        #         "train_period_in_hours": 720,
        #         "predict_period_in_hours": 12,
        #         "max_forecast_horizon": pd.Timedelta(hours=12),
        #         "forecast_frequency": pd.Timedelta(hours=12),
        #         "end_date": pd.Timestamp(
        #             "2025-01-15T12:00:00+01", tz="Europe/Amsterdam"
        #         )
        #         + pd.Timedelta(hours=12),
        #         "max_training_period": pd.Timedelta(days=365),
        #         "save_belief_time": pd.Timestamp(
        #             "2025-01-15T12:23:58.387422+01", tz="Europe/Amsterdam"
        #         ),
        #         "n_cycles": 1,
        #     },
        # ),
        # Case 3: forecast-frequency = 12 hours
        #
        # User expects to get forecasts for the default FM planning horizon from a new viewpoint every 12 hours.
        # Specifically, we expect:
        #    - predict-period = FM planning horizon
        #    - max-forecast-horizon = predict-period (actual horizons are 48, 36, 24 and 12)
        #    - retraining-period = FM planning horizon
        #    - 1 cycle, 4 belief times
        (
            {"forecast-frequency": "PT12H"},
            {
                "predict_start": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01", tz="Europe/Amsterdam"
                ).floor("1h"),
                "start_date": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01", tz="Europe/Amsterdam"
                ).floor("1h")
                - pd.Timedelta(days=30),
                "train_period_in_hours": 720,
                "predict_period_in_hours": 48,
                "max_forecast_horizon": pd.Timedelta(hours=48),
                "forecast_frequency": pd.Timedelta(hours=12),
                "end_date": pd.Timestamp(
                    "2025-01-15T12:00:00+01", tz="Europe/Amsterdam"
                )
                + pd.Timedelta(hours=48),
                "max_training_period": pd.Timedelta(days=365),
                "save_belief_time": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01", tz="Europe/Amsterdam"
                ),
                "n_cycles": 1,
            },
        ),
        # Case 4: (config) retraining-period = 12 hours
        #
        # User expects to get forecasts for the default FM planning horizon from a new viewpoint every 12 hours (retraining at every viewpoint).
        # Specifically, we expect:
        #    - predict-period = FM planning horizon
        #    - max-forecast-horizon = predict-period (actual horizons are 48, 36, 24 and 12)
        #    - forecast-frequency = predict-period (NOT capped by retraining-period, no param changes based on config)
        #    - 1 cycle, 1 belief time
        (
            {
                "retrain-frequency": "PT12H",
                "end-date": "2025-01-17T12:00:00+01:00",
            },
            {
                "predict_start": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01", tz="Europe/Amsterdam"
                ).floor("1h"),
                "start_date": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01", tz="Europe/Amsterdam"
                ).floor("1h")
                - pd.Timedelta(days=30),
                "train_period_in_hours": 720,
                "predict_period_in_hours": 48,
                "max_forecast_horizon": pd.Timedelta(hours=48),
                "forecast_frequency": pd.Timedelta(hours=48),
                "end_date": pd.Timestamp(
                    "2025-01-17T12:00:00+01", tz="Europe/Amsterdam"
                ),
                "max_training_period": pd.Timedelta(days=365),
                "save_belief_time": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01", tz="Europe/Amsterdam"
                ),
                "n_cycles": 1,
            },
        ),
        # Case 5: predict-period = 10 days and max-forecast-horizon = 12 hours
        #
        # User expects to get forecasts for the next 10 days from a new viewpoint every 12 hours.
        #    - forecast-frequency = max-forecast-horizon = 12 hours
        #    - retraining-frequency = FM planning horizon
        #    - 5 cycles, 20 belief times
        # (
        #     {
        #         "duration": "P10D",
        #         "max-forecast-horizon": "PT12H",
        #     },
        #     {
        #         "predict_start": pd.Timestamp(
        #             "2025-01-15T12:23:58.387422+01", tz="Europe/Amsterdam"
        #         ).floor("1h"),
        #         "start_date": pd.Timestamp(
        #             "2025-01-15T12:23:58.387422+01", tz="Europe/Amsterdam"
        #         ).floor("1h")
        #         - pd.Timedelta(days=30),
        #         "train_period_in_hours": 720,
        #         "predict_period_in_hours": 240,
        #         "max_forecast_horizon": pd.Timedelta(hours=12),
        #         "forecast_frequency": pd.Timedelta(hours=12),
        #         "end_date": pd.Timestamp(
        #             "2025-01-15T12:00:00+01", tz="Europe/Amsterdam"
        #         )
        #         + pd.Timedelta(days=10),
        #         "max_training_period": pd.Timedelta(days=365),
        #         "save_belief_time": pd.Timestamp(
        #             "2025-01-15T12:23:58.387422+01", tz="Europe/Amsterdam"
        #         ),
        #         "n_cycles": 5,
        #     },
        # ),
        # Case 6: predict-period = 12 hours and max-forecast-horizon = 10 days
        #
        # User expects that FM complains: the max-forecast-horizon should be lower than the predict-period
        #    - forecast-frequency = predict-period
        #    - retraining-frequency = FM planning horizon
        #    - 1 cycle, 1 belief time
        (
            {
                "retrain-frequency": "PT12H",
                "max-forecast-horizon": "P10D",
            },
            {
                "predict_start": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01", tz="Europe/Amsterdam"
                ).floor("1h"),
                "start_date": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01", tz="Europe/Amsterdam"
                ).floor("1h")
                - pd.Timedelta(days=30),
                "train_period_in_hours": 720,
                "predict_period_in_hours": 12,
                "max_forecast_horizon": pd.Timedelta(days=10),
                "forecast_frequency": pd.Timedelta(days=10),
                "end_date": pd.Timestamp(
                    "2025-01-15T12:00:00+01", tz="Europe/Amsterdam"
                )
                + pd.Timedelta(hours=12),
                "max_training_period": pd.Timedelta(days=365),
                "save_belief_time": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01", tz="Europe/Amsterdam"
                ),
                "n_cycles": 1,
            },
        ),
        # Test defaults when only an end date is given
        # We expect training period of 30 days before predict start and prediction period of 5 days after predict start, with predict start at server now (floored to hour).
        # 1 cycle expected (1 belief time for forecast) given the forecast frequency equal defaulted to prediction period of 5 days.
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
                ),  # default training period 30 days before predict start
                "end-date": pd.Timestamp(
                    "2025-01-20T12:00:00+01",
                    tz="Europe/Amsterdam",
                ),
                "train-period-in-hours": 720,  # from start date to predict start
                "predict-period-in-hours": 120,  # from predict start to end date
                "forecast-frequency": pd.Timedelta(
                    days=5
                ),  # duration between predict start and end date
                "max-forecast-horizon": pd.Timedelta(
                    days=5
                ),  # duration between predict start and end date
                # default values
                "max-training-period": pd.Timedelta(days=365),
                # server now
                "save-belief-time": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01",
                    tz="Europe/Amsterdam",
                ),
                "n_cycles": 1,
            },
        ),
        # Test when both start and end dates are given
        # We expect training period of 26.5 days (636 hours) from the given start date and predict start, prediction period of 108 hours duration from predict start to end date, with predict_start at server now (floored to hour).
        # 1 cycle expected (1 belief_time for forecast) given the forecast frequency equal defaulted to prediction period
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
                "predict-period-in-hours": 108,  # hours from predict start to end date
                "train-period-in-hours": 636,  # hours between start date and predict start
                "max-forecast-horizon": pd.Timedelta(days=4)
                + pd.Timedelta(hours=12),  # duration between predict start and end date
                "forecast-frequency": pd.Timedelta(days=4)
                + pd.Timedelta(hours=12),  # duration between predict start and end date
                # default values
                "max-training-period": pd.Timedelta(days=365),
                # server now
                "save-belief-time": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01",
                    tz="Europe/Amsterdam",
                ),
                "n_cycles": 1,
            },
        ),
        # Test when only end date is given with a training period
        # We expect the start date to be computed with respect to now. (training period before now (floored)).
        # We expect training period of 30 days before predict start and prediction period of 48 hours after predict start, with predict start at server now (floored to hour).
        # 1 cycle expected (1 belief_time for forecast) given the forecast frequency equal defaulted to prediction period
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
                "train-period-in-hours": 72,  # from start date to predict start
                "predict-period-in-hours": 120,  # from predict start to end date
                "max-forecast-horizon": pd.Timedelta(
                    days=5
                ),  # duration between predict start and end date
                "forecast-frequency": pd.Timedelta(
                    days=5
                ),  # duration between predict start and end date
                # default values
                "max-training-period": pd.Timedelta(days=365),
                # server now
                "save-belief-time": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01",
                    tz="Europe/Amsterdam",
                ),
                "n_cycles": 1,
            },
        ),
        # Test when only start date is given with a training period
        # We expect the predict start to be computed with respect to the start date (training period after start date).
        # We set training period of 3 days, we expect a prediction period to default 48 hours after predict start, with predict start at server now (floored to hour).
        # 1 cycle expected (1 belief_time for forecast) given the forecast frequency equal defaulted to prediction period
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
                "max-forecast-horizon": pd.Timedelta(
                    days=2
                ),  # duration between predict start and end date
                "forecast-frequency": pd.Timedelta(
                    days=2
                ),  # duration between predict start and end date
                # default values
                "predict-period-in-hours": 48,
                "max-training-period": pd.Timedelta(days=365),
                # the belief time of the forecasts will be calculated from start-predict-date and max-forecast-horizon and forecast-frequency
                "save-belief-time": None,
                "n_cycles": 1,
            },
        ),
        # Test when only start date is given with a retrain frequency (prediction period)
        # We expect the predict start to be computed with respect to the start date (training period after start date).
        # We set training period of 3 days, we expect a prediction period to default 48 hours after predict start, with predict start at server now (floored to hour).
        # 1 cycle expected (1 belief_time for forecast) given the forecast frequency equal defaulted to prediction period
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
                "max-forecast-horizon": pd.Timedelta(
                    days=3
                ),  # duration between predict-start and end-date
                "forecast-frequency": pd.Timedelta(
                    days=3
                ),  # duration between predict-start and end-date
                # default values
                "max-training-period": pd.Timedelta(days=365),
                # server now
                "save-belief-time": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01",
                    tz="Europe/Amsterdam",
                ),
                "n_cycles": 1,
            },
        ),
        # Test when only start date is given with both training period 20 days and retrain frequency 3 days
        # We expect the predict start to be computed with respect to the start date (training period after start date).
        # 1 cycle expected (1 belief_time for forecast) given the forecast frequency equal defaulted to prediction period
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
                "max-forecast-horizon": pd.Timedelta(days=3),  # predict period duration
                "forecast-frequency": pd.Timedelta(days=3),  # predict period duration
                # default values
                "max-training-period": pd.Timedelta(days=365),
                # the belief time of the forecasts will be calculated from start-predict-date and max-forecast-horizon and forecast-frequency
                "save-belief-time": None,
            },
        ),
        # Test when only end date is given with a prediction period: we expect the train start and predict start to both be computed with respect to the end date.
        # we expect training period of 30 days before predict_start and prediction period of 3 days after predict_start, with predict_start at server now (floored to hour).
        # we expect 2 cycles from the retrain frequency and predict period given the end date
        (
            {
                "end-date": "2025-01-21T12:00:00+01:00",
                "retrain-frequency": "P3D",
            },
            {
                "end-date": pd.Timestamp(
                    "2025-01-21T12:00:00+01", tz="Europe/Amsterdam"
                ),
                "predict-start": pd.Timestamp(
                    "2025-01-15T12:00:00+01", tz="Europe/Amsterdam"
                ),
                "start-date": pd.Timestamp(
                    "2025-01-15T12:00:00+01", tz="Europe/Amsterdam"
                )
                - pd.Timedelta(days=30),
                "predict-period-in-hours": 72,
                "train-period-in-hours": 720,
                "max-forecast-horizon": pd.Timedelta(
                    days=3
                ),  # duration between predict start and end date (retrain frequency)
                "forecast-frequency": pd.Timedelta(
                    days=3
                ),  # duration between predict start and end date (retrain frequency)
                # default values
                "max-training-period": pd.Timedelta(days=365),
                # server now
                "save-belief-time": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01",
                    tz="Europe/Amsterdam",
                ),
                "n_cycles": 2,  # we expect 2 cycles from the retrain frequency and predict period given the end date
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
        # Convert kebab-case key to snake_case to match data dictionary keys returned by schema
        snake_key = kebab_to_snake(k)
        assert data[snake_key] == v, f"{k} did not match expectations."
