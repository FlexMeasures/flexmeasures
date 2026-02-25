import pytest

from marshmallow import ValidationError
import pandas as pd

from flexmeasures.data.schemas.forecasting.pipeline import (
    ForecasterParametersSchema,
    TrainPredictPipelineConfigSchema,
)
from flexmeasures.data.schemas.utils import kebab_to_snake


@pytest.mark.parametrize(
    ["timing_input", "expected_timing_output"],
    [
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
                # "start-date": pd.Timestamp(
                #     "2025-01-15T12:23:58.387422+01", tz="Europe/Amsterdam"
                # ).floor("1h")
                # - pd.Timedelta(days=30),
                # default prediction period 48 hours after predict start
                "end-date": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01", tz="Europe/Amsterdam"
                ).floor("1h")
                + pd.Timedelta(hours=48),
                # these are set by the schema defaults
                "predict-period-in-hours": 48,
                "max-forecast-horizon": pd.Timedelta(days=2),
                # "train-period-in-hours": 24 * 30,
                # "retrain_frequency": 2 * 24,
                # "max-training-period": pd.Timedelta(days=365),
                "forecast-frequency": pd.Timedelta(days=2),
                # the one belief time corresponds to server now
                "save-belief-time": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01",
                    tz="Europe/Amsterdam",
                ),
                "m_viewpoints": 1,
            },
        ),
        # Case 1: predict-period = 12 hours
        #
        # User expects to get forecasts for the next 12 hours from a single viewpoint.
        # Specifically, we expect:
        #    - max-forecast-horizon = predict-period = 12 hours
        #    - forecast-frequency = predict-period = 12 hours
        #    - (config) retraining-frequency = FM planning horizon, but capped by predict-period, so 12 hours
        #    - 1 cycle, 1 belief time
        #    - training-period = 30 days
        (
            {"duration": "PT12H"},
            {
                "predict_start": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01", tz="Europe/Amsterdam"
                ).floor("1h"),
                # "start_date": pd.Timestamp(
                #     "2025-01-15T12:23:58.387422+01", tz="Europe/Amsterdam"
                # ).floor("1h")
                # - pd.Timedelta(days=30),
                # "train_period_in_hours": 24 * 30,
                "predict_period_in_hours": 12,
                "max_forecast_horizon": pd.Timedelta(hours=12),
                "forecast_frequency": pd.Timedelta(hours=12),
                "end_date": pd.Timestamp(
                    "2025-01-15T12:00:00+01", tz="Europe/Amsterdam"
                )
                + pd.Timedelta(hours=12),
                # "retrain_frequency": 2 * 24,
                # "max_training_period": pd.Timedelta(days=365),
                "save_belief_time": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01", tz="Europe/Amsterdam"
                ),
                "m_viewpoints": 1,
            },
        ),
        # Case 2: max-forecast-horizon = 12 hours  # here we have issue that predict period is defaulted to 48 hours, but max-forecast-horizon is set to 12 hours, which should be less than or equal to predict-period
        #
        # User expects to get forecasts for the next 12 hours from a single viewpoint (same as case 1).
        # Specifically, we expect:
        #    - predict-period = 12 hours
        #    - forecast-frequency = max-forecast-horizon = 12 hours
        #    - retraining-period = FM planning horizon
        #    - 1 cycle, 1 belief time
        # These expectations are encoded in default 1 of ForecasterParametersSchema.resolve_config
        (
            {"max-forecast-horizon": "PT12H"},
            {
                "predict_start": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01", tz="Europe/Amsterdam"
                ).floor("1h"),
                # "start_date": pd.Timestamp(
                #     "2025-01-15T12:23:58.387422+01", tz="Europe/Amsterdam"
                # ).floor("1h")
                # - pd.Timedelta(days=30),
                "end_date": pd.Timestamp(
                    "2025-01-15T12:00:00+01", tz="Europe/Amsterdam"
                )
                + pd.Timedelta(hours=48),
                # "train_period_in_hours": 30 * 24,
                "predict_period_in_hours": 12,
                "max_forecast_horizon": pd.Timedelta(hours=12),
                "forecast_frequency": pd.Timedelta(hours=12),
                # "retrain_frequency": 2 * 24,
                # "max_training_period": pd.Timedelta(days=365),
                "save_belief_time": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01", tz="Europe/Amsterdam"
                ),
                "m_viewpoints": 1,
            },
        ),
        # Case 3: forecast-frequency = 12 hours
        # todo: add to description that this should really be used in combination with the predict-start field
        #
        # User expects to get forecasts for the default FM planning horizon from a new viewpoint every 12 hours.
        # Specifically, we expect:
        #    - predict-period = FM planning horizon
        #    - max-forecast-horizon = predict-period (actual horizons are 48, 36, 24 and 12)
        #    - retraining-period = FM planning horizon
        #    - 1 cycle, 4 belief times
        (
            {
                "start": "2025-01-15T12:00:00+01:00",
                "forecast-frequency": "PT12H",
            },
            {
                "predict_start": pd.Timestamp(
                    "2025-01-15T12:00:00.000+01", tz="Europe/Amsterdam"
                ),
                # "start_date": pd.Timestamp(
                #     "2025-01-15T12:23:58.387422+01", tz="Europe/Amsterdam"
                # ).floor("1h")
                # - pd.Timedelta(days=30),
                # "train_period_in_hours": 30 * 24,
                "predict_period_in_hours": 48,
                "max_forecast_horizon": pd.Timedelta(hours=48),
                "forecast_frequency": pd.Timedelta(hours=12),
                "end_date": pd.Timestamp(
                    "2025-01-15T12:00:00+01", tz="Europe/Amsterdam"
                )
                + pd.Timedelta(hours=48),
                # "max_training_period": pd.Timedelta(days=365),
                # "retrain-frequency": 2 * 24,
                # this is the first belief time of the four belief times
                "save_belief_time": pd.Timestamp(
                    "2025-01-15T12:00:00.00+01", tz="Europe/Amsterdam"
                ),
                "m_viewpoints": 4,
            },
        ),
        # Case 4: predict-period = 10 days and max-forecast-horizon = 12 hours
        #
        # User expects to get a ValidationError for having set parameters that won't give complete coverage of the predict-period.
        (
            {
                "duration": "P10D",
                "max-forecast-horizon": "PT12H",
            },
            ValidationError(
                {
                    "max_forecast_horizon": [
                        "This combination of parameters will not yield forecasts for the entire prediction window."
                    ]
                }
            ),
        ),
        # Case 5: predict-period = 12 hours and max-forecast-horizon = 10 days
        #
        # User expects that FM complains: the max-forecast-horizon should be lower than the predict-period
        #    - forecast-frequency = predict-period
        #    - retraining-frequency = FM planning horizon
        #    - 1 cycle, 1 belief time
        (
            {
                "duration": "PT12H",
                "max-forecast-horizon": "P10D",
            },
            ValidationError(
                {
                    "max_forecast_horizon": [
                        "max-forecast-horizon must be less than or equal to predict-period"
                    ]
                }
            ),
        ),
        # Case 6: end-date = almost 5 days after now
        #
        # User expects to get forecasts for the next 5 days (from server now floored to 1 hour) with a default 30-day training period
        #    - predict-period = 5 days
        #    - forecast-frequency = predict-period
        #    - retraining-frequency = FM planning horizon
        #    - 1 cycle, 1 belief time
        #    - training-period = 30 days
        (
            {"end": "2025-01-20T12:00:00+01:00"},
            {
                "predict-start": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01",
                    tz="Europe/Amsterdam",
                ).floor("1h"),
                # "start-date": pd.Timestamp(
                #     "2025-01-15T12:23:58.387422+01",
                #     tz="Europe/Amsterdam",
                # ).floor("1h")
                # - pd.Timedelta(
                #     days=30
                # ),  # default training period 30 days before predict start
                "end-date": pd.Timestamp(
                    "2025-01-20T12:00:00+01",
                    tz="Europe/Amsterdam",
                ),
                # "train-period-in-hours": 30 * 24,  # from start date to predict start
                "predict-period-in-hours": 120,  # from predict start to end date
                "forecast-frequency": pd.Timedelta(
                    days=5
                ),  # default forecast frequency
                "max-forecast-horizon": pd.Timedelta(
                    days=5
                ),  # duration between predict start and end date
                # default values
                # "retrain_frequency": 2 * 24,
                # "max-training-period": pd.Timedelta(days=365),
                # server now
                "save-belief-time": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01",
                    tz="Europe/Amsterdam",
                ),
                "m_viewpoints": 1,
            },
        ),
        # Case 7: end-date = almost 4.5 days after now, train-start is 26.5 days before now
        #
        # User expects to get forecasts for the next 4.5 days (from server now floored to 1 hour) with a custom 636-hour training period
        #    - predict-period = 108 hours
        #    - forecast-frequency = predict-period
        #    - retraining-frequency = FM planning horizon
        #    - 1 cycle, 1 belief time
        #    - training-period = 636 hours
        (
            {
                # "train-start": "2024-12-20T00:00:00+01:00",
                "end": "2025-01-20T00:00:00+01:00",
            },
            {
                # "start-date": pd.Timestamp(
                #     "2024-12-20T00:00:00+01", tz="Europe/Amsterdam"
                # ),
                "end-date": pd.Timestamp(
                    "2025-01-20T00:00:00+01", tz="Europe/Amsterdam"
                ),
                "predict-start": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01",
                    tz="Europe/Amsterdam",
                ).floor("1h"),
                "predict-period-in-hours": 108,  # hours from predict start to end date
                # "train-period-in-hours": 636,  # hours between start date and predict start
                "max-forecast-horizon": pd.Timedelta(hours=108),
                "forecast-frequency": pd.Timedelta(hours=108),
                # "retrain_frequency": 2 * 24,
                # "max-training-period": pd.Timedelta(days=365),
                # server now
                "save-belief-time": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01",
                    tz="Europe/Amsterdam",
                ),
                "m_viewpoints": 1,
            },
        ),
        # Case 8: end-date is given with train-period = 3 days
        #
        # User expects the start date to be computed from the inferred predict-start and train-period.
        # Specifically, we expect:
        #    - predict-start = server now floored to sensor resolution
        #    - train-period = 3 days (72 hours)
        #    - predict-period = 5 days (from predict-start to end-date)
        #    - max-forecast-horizon = predict-period = 5 days
        #    - forecast-frequency = predict-period = 5 days
        #    - retrain-frequency = FM planning horizon
        #    - 1 cycle, 1 belief time
        (
            {
                "end": "2025-01-20T12:00:00+01:00",
                # "train-period": "P3D",
            },
            {
                "end-date": pd.Timestamp(
                    "2025-01-20T12:00:00+01", tz="Europe/Amsterdam"
                ),
                "predict-start": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01",
                    tz="Europe/Amsterdam",
                ).floor("1h"),
                # "start-date": pd.Timestamp(
                #     "2025-01-15T12:00:00+01", tz="Europe/Amsterdam"
                # )
                # - pd.Timedelta(days=3),
                # "train-period-in-hours": 72,  # from start date to predict start
                "predict-period-in-hours": 120,  # from predict start to end date
                "max-forecast-horizon": pd.Timedelta(
                    days=5
                ),  # duration between predict start and end date
                "forecast-frequency": pd.Timedelta(days=5),
                # default values
                # "retrain_frequency": 2 * 24,
                # "max-training-period": pd.Timedelta(days=365),
                # server now
                "save-belief-time": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01",
                    tz="Europe/Amsterdam",
                ),
                "m_viewpoints": 1,
            },
        ),
        # Case 9: train-start is given with predict-period duration = 3 days
        #
        # User expects predict-start to remain based on server now (no train-period given).
        # Specifically, we expect:
        #    - predict-start = server now floored to sensor resolution
        #    - predict-period = 3 days
        #    - end-date = predict-start + 3 days
        #    - train-period derived from train-start to predict-start
        #    - max-forecast-horizon = predict-period = 3 days
        #    - forecast-frequency = predict-period = 3 days
        #    - retrain-frequency = FM planning horizon
        #    - 1 cycle, 1 belief time
        (
            {
                # "train-start": "2024-12-25T00:00:00+01:00",
                "duration": "P3D",
            },
            {
                # "start-date": pd.Timestamp(
                #     "2024-12-25T00:00:00+01", tz="Europe/Amsterdam"
                # ),
                "predict-start": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01",
                    tz="Europe/Amsterdam",
                ).floor("1h"),
                "end-date": pd.Timestamp(
                    "2025-01-15T12:00:00+01", tz="Europe/Amsterdam"
                )
                + pd.Timedelta(days=3),
                "predict-period-in-hours": 72,
                # "train-period-in-hours": 516,  # from train-start to predict-start
                "max-forecast-horizon": pd.Timedelta(
                    days=3
                ),  # duration between predict-start and end-date
                "forecast-frequency": pd.Timedelta(days=3),
                # default values
                # "retrain_frequency": 2 * 24,
                # "max-training-period": pd.Timedelta(days=365),
                # server now
                "save-belief-time": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01",
                    tz="Europe/Amsterdam",
                ),
                "m_viewpoints": 1,
            },
        ),
        # Case 10: forecast-frequency = 5 days, predict-period = 10 days
        #
        # User expects to get forecasts for 10 days from two unique viewpoints 5 days apart.
        # Specifically, we expect:
        #    - predict-period = 10 days
        #    - max-forecast-horizon = predict-period (actual horizons are 10 days and 5 days)
        #    - forecast-frequency = 5 days
        #    - retrain-frequency = FM planning horizon
        #    - 2 cycles, 2 belief times
        (
            {
                "duration": "P10D",
                "forecast-frequency": "P5D",
            },
            {
                "end-date": pd.Timestamp(
                    "2025-01-25T12:00:00+01", tz="Europe/Amsterdam"
                ),
                "predict-start": pd.Timestamp(
                    "2025-01-15T12:00:00+01", tz="Europe/Amsterdam"
                ),
                # "start-date": pd.Timestamp(
                #     "2025-01-15T12:00:00+01", tz="Europe/Amsterdam"
                # )
                # - pd.Timedelta(days=30),
                "predict-period-in-hours": 240,  # from predict start to end date
                # "train-period-in-hours": 30 * 24,
                "max-forecast-horizon": pd.Timedelta(
                    days=10
                ),  # duration between predict start and end date
                "forecast-frequency": pd.Timedelta(hours=120),
                # default values
                # "max-training-period": pd.Timedelta(days=365),
                # "retrain-frequency": 2 * 24,
                # server now
                "save-belief-time": pd.Timestamp(
                    "2025-01-15T12:23:58.387422+01",
                    tz="Europe/Amsterdam",
                ),
                "m_viewpoints": 2,  # we expect 2 cycles from the retrain frequency and predict period given the end date
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

    if isinstance(expected_timing_output, ValidationError):
        with pytest.raises(ValidationError) as exc:
            ForecasterParametersSchema().load(
                {
                    "sensor": 1,
                    **timing_input,
                }
            )
        assert exc.value.messages == expected_timing_output.messages
        return
    data = ForecasterParametersSchema().load(
        {
            "sensor": 1,
            **timing_input,
        }
    )
    # breakpoint()
    for k, v in expected_timing_output.items():
        # Convert kebab-case key to snake_case to match data dictionary keys returned by schema
        snake_key = kebab_to_snake(k)
        assert data[snake_key] == v, f"{k} did not match expectations."


@pytest.mark.parametrize(
    ["timing_input", "expected_timing_output"],
    [
        # Case 0: (config) retraining-period = 12 hours
        #
        # User expects to get forecasts for the default FM planning horizon from a new viewpoint every 12 hours (retraining at every viewpoint).
        # Specifically from config, we expect:
        #    - train-period = default 30 days
        #    - max-training-period = default 365 days
        #    - retraining-frequency = 12 hours
        #    - train-period-in-hours = 720 (30 days)
        (
            {
                "retrain-frequency": "PT12H",
                # "end-date": "2025-01-17T12:00:00+01:00",
            },
            {
                "model": "CustomLGBM",
                "train-period": pd.Timedelta(days=30),
                "max-training-period": pd.Timedelta(days=365),
                "retrain-frequency": pd.Timedelta(hours=12),
                "train-period-in-hours": 24 * 30,
            },
        ),
        # Case 1: train-start is given with train-period = 3 days
        #
        # User expects predict-start to be derived from train-start + train-period.
        # Specifically from config, we expect:
        #    - train-period = 3 days
        #    - max-training-period = default 365 days
        #    - retraining-frequency = FM planning horizon
        #    - train-period-in-hours = 72 (3 days)
        (
            {
                "train-start": "2024-12-25T00:00:00+01:00",
                "train-period": "P3D",
            },
            {
                "model": "CustomLGBM",
                "train-period": pd.Timedelta(days=3),
                "max-training-period": pd.Timedelta(days=365),
                "retrain-frequency": pd.Timedelta(days=2),
                "train-period-in-hours": 24 * 3,
            },
        ),
        # Case 2: train-start is given with train-period = 20 days
        #
        # User expects both predict-start and end-date to be derived from train-start.
        # Specifically from config, we expect:
        #    - train-period = 20 days
        #    - max-training-period = default 365 days
        #    - retraining-frequency = FM planning horizon
        #    - train-period-in-hours = 480 (20 days)
        (
            {
                "train-start": "2024-12-01T00:00:00+01:00",
                "train-period": "P20D",
            },
            {
                "model": "CustomLGBM",
                "train-period": pd.Timedelta(days=20),
                "max-training-period": pd.Timedelta(days=365),
                "retrain-frequency": pd.Timedelta(days=2),
                "train-period-in-hours": 24 * 20,
            },
        ),
        # Case 3: only end is given with retrain-frequency = 3 days
        #
        # User expects train start and predict start to be derived from end-date and defaults.
        # Specifically from config, we expect:
        #    - train-period = default 30 days
        #    - max-training-period = default 365 days
        #    - retraining-frequency = 12 hours
        #    - train-period-in-hours = 720 (30 days)
        (
            {
                # "end-date": "2025-01-21T12:00:00+01:00",
                "retrain-frequency": "P3D",  # only comes into play if forecast-frequency is lower than retrain-frequency, which here it is not
            },
            {
                "model": "CustomLGBM",
                "train-period": pd.Timedelta(days=30),
                "max-training-period": pd.Timedelta(days=365),
                "retrain-frequency": pd.Timedelta(days=3),
                "train-period-in-hours": 24 * 30,
            },
        ),
    ],
)
def test_timing_parameters_of_forecaster_config_schema(
    setup_dummy_sensors, freeze_server_now, timing_input, expected_timing_output
):
    freeze_server_now(
        pd.Timestamp("2025-01-15T12:23:58.387422+01", tz="Europe/Amsterdam")
    )

    if isinstance(expected_timing_output, ValidationError):
        with pytest.raises(ValidationError) as exc:
            TrainPredictPipelineConfigSchema().load(
                {
                    **timing_input,
                }
            )
        assert exc.value.messages == expected_timing_output.messages
        return
    data = TrainPredictPipelineConfigSchema().load(
        {
            **timing_input,
        }
    )

    for k, v in expected_timing_output.items():
        # Convert kebab-case key to snake_case to match data dictionary keys returned by schema
        snake_key = kebab_to_snake(k)
        assert data[snake_key] == v, f"{k} did not match expectations."
