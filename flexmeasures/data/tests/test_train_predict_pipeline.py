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
                "max_forecast_horizon": 1,
                "forecast_frequency": 1,
                "probabilistic": False,
            },
            (ValidationError, "predict-period must be greater than 0"),
        ),
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
                "predict_period": 1,
                "max_forecast_horizon": 1,
                "forecast_frequency": 1,
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
    sensor_id = sensor.id
    kwargs["sensor"] = sensor_id
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
            kwargs["forecast_frequency"] * timedelta(hours=1)
        )
        n_horizons = kwargs["max_forecast_horizon"]
        assert (
            len(forecasts) == n_cycles * n_horizons
        ), f"we expect 1 forecast per horizon for each cycle within the prediction window, and {n_cycles} cycles with each {n_horizons} horizons"
        assert (
            forecasts.lineage.number_of_belief_times == n_cycles
        ), f"we expect 1 belief time per cycle, and {n_cycles} cycles"
        assert "CustomLGBM" in str(
            forecasts.lineage.sources[0]
        ), "string representation of Source should mention the used model"
