from __future__ import annotations

import pytest

import json
from marshmallow import ValidationError

from flexmeasures.data.schemas.forecasting.pipeline import ForecastingPipelineSchema
from flexmeasures.data.models.forecasting.pipelines import TrainPredictPipeline


@pytest.mark.parametrize(
    ["kwargs", "expected_error"],
    [
        (
            {
                "sensors": {"PV": 1},
                "regressors": "autoregressive",
                "target": "PV",
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
            (ValidationError, "--predict-period must be greater than 0"),
        ),
        (
            {
                "sensors": {"PV": 1},
                "regressors": "autoregressive",
                "target": "PV",
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
            False,
        ),
        # (
        #     {
        #         "sensors": {"PV": 1},
        #         "regressors": "autoregressive",
        #         "target": "PV",
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
def test_bad_timing_params(
    setup_fresh_test_forecast_data,
    kwargs,
    expected_error: bool | tuple[type[BaseException], str],
):
    sensor = setup_fresh_test_forecast_data["solar-sensor"]
    sensor_id = sensor.id
    kwargs["sensors"]["PV"] = sensor_id
    kwargs["sensors"] = json.dumps(
        kwargs["sensors"]
    )  # schema expects to load serialized kwargs
    if expected_error:
        with pytest.raises(expected_error[0]) as e_info:
            kwargs = ForecastingPipelineSchema().load(kwargs)
            pipeline = TrainPredictPipeline(**kwargs)
            pipeline.run()
        assert expected_error[1] in str(e_info)
    else:
        kwargs = ForecastingPipelineSchema().load(kwargs)
        pipeline = TrainPredictPipeline(**kwargs)
        beliefs_before = len(sensor.search_beliefs())
        pipeline.run()
        beliefs_after = len(sensor.search_beliefs())
        assert beliefs_after > beliefs_before
