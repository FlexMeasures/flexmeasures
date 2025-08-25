from __future__ import annotations

import pytest

from datetime import timedelta

from marshmallow import ValidationError

from flexmeasures.data.schemas.forecasting.pipeline import ForecastingPipelineSchema
from flexmeasures.data.models.forecasting.pipelines import TrainPredictPipeline


@pytest.mark.parametrize(
    ["kwargs", "expected_error"],
    [
        (
            {
                "sensor": 1,
                "model_save_dir": "flexmeasures/data/models/forecasting/artifacts/models",
                "output_path": None,
                "start_date": "2025-01-01T00:00+02:00",
                "end_date": "2025-01-03T00:00+02:00",
                "train_period": 2,
                "sensor_to_save": None,
                "start_predict_date": "2025-01-02T00:00+02:00",
                "predict_period": 0,  # 0 days
                "max_forecast_horizon": "PT1H",
                "forecast_frequency": "PT1H",
                "probabilistic": False,
            },
            (ValidationError, "predict-period must be greater than 0"),
        ),
        (
            {
                "sensor": 1,
                "future_regressors": 2,
                "model_save_dir": "flexmeasures/data/models/forecasting/artifacts/models",
                "output_path": None,
                "start_date": "2025-01-01T00:00+02:00",
                "end_date": "2025-01-03T00:00+02:00",
                "train_period": 2,
                "sensor_to_save": None,
                "start_predict_date": "2025-01-02T00:00+02:00",
                "predict_period": 1,
                "max_forecast_horizon": "PT1H",
                "forecast_frequency": "PT1H",
                "probabilistic": False,
            },
            None,
        ),
        # (
        #     {
        #         "sensor": 1,
        #         "model_save_dir": "flexmeasures/data/models/forecasting/artifacts/models",
        #         "output_path": None,
        #         "start_date": "2025-07-01T00:00+02:00",
        #         "end_date": "2025-07-12T00:00+02:00",
        #         "train_period": 24.0,
        #         "sensor_to_save": 1,
        #         "start_predict_date": "2025-07-11T17:26+02:00",
        #         "predict_period": 24,
        #         "max_forecast_horizon": 24,
        #         "forecast_frequency": 1,
        #         "probabilistic": False,
        #     },
        #     (ValidationError, "Try increasing the --end-date."),
        # )
    ],
)
def test_train_predict_pipeline(
    setup_fresh_test_forecast_data,
    kwargs,
    expected_error: bool | tuple[type[BaseException], str],
):
    sensor = setup_fresh_test_forecast_data["solar-sensor"]
    regressor = setup_fresh_test_forecast_data["irradiance-sensor"]
    kwargs["sensor"] = sensor.id
    kwargs["future_regressors"] = f"{regressor.id}"
    if expected_error:
        with pytest.raises(expected_error[0]) as e_info:
            kwargs = ForecastingPipelineSchema().load(kwargs)
            pipeline = TrainPredictPipeline(**kwargs)
            pipeline.run()
        assert expected_error[1] in str(e_info)
    else:
        kwargs = ForecastingPipelineSchema().load(kwargs)
        pipeline = TrainPredictPipeline(**kwargs)
        pipeline.run()
        forecasts = sensor.search_beliefs(source="forecaster")
        n_cycles = (kwargs["end_date"] - kwargs["predict_start"]) / (
            kwargs["forecast_frequency"] * kwargs["target"].event_resolution
        )
        # 1 hour of forecasts is saved over 4 15-minute resolution events
        n_events_per_horizon = timedelta(hours=1) / kwargs["target"].event_resolution
        n_hourly_horizons = kwargs["max_forecast_horizon"] // n_events_per_horizon
        assert (
            len(forecasts) == n_cycles * n_hourly_horizons * n_events_per_horizon
        ), f"we expect 4 forecasts per horizon for each cycle within the prediction window, and {n_cycles} cycles with each {n_hourly_horizons} hourly horizons"
        assert (
            forecasts.lineage.number_of_belief_times == n_cycles
        ), f"we expect 1 belief time per cycle, and {n_cycles} cycles"
        assert "CustomLGBM" in str(
            forecasts.lineage.sources[0]
        ), "string representation of Source should mention the used model"
