from __future__ import annotations

import pytest

from datetime import timedelta

from marshmallow import ValidationError

from flexmeasures.data.models.forecasting.pipelines import TrainPredictPipeline


@pytest.mark.parametrize(
    ["kwargs", "expected_error"],
    [
        (
            {
                "sensor": "solar-sensor",
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
                "sensor": "solar-sensor",
                "future_regressors": ["irradiance-sensor"],
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
        #         "sensor": "solar-sensor",
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
    sensor = setup_fresh_test_forecast_data[kwargs["sensor"]]
    kwargs["sensor"] = sensor.id
    regressors = [
        setup_fresh_test_forecast_data[regressor_name]
        for regressor_name in kwargs.get("future_regressors", [])
    ]
    if regressors:
        kwargs["future_regressors"] = ",".join(
            [str(regressor.id) for regressor in regressors]
        )
    if expected_error:
        with pytest.raises(expected_error[0]) as e_info:
            pipeline = TrainPredictPipeline(config=kwargs)
            pipeline.run()
        assert expected_error[1] in str(e_info)
    else:
        pipeline = TrainPredictPipeline(config=kwargs)

        # Check pipeline properties
        for attr in ("past_regressors", "future_regressors"):
            if kwargs.get(attr):
                assert hasattr(pipeline, attr)

        pipeline.run()
        forecasts = sensor.search_beliefs(source_types=["forecaster"])
        config = pipeline._config
        n_cycles = (config["end_date"] - config["predict_start"]) / (
            config["forecast_frequency"] * config["target"].event_resolution
        )
        # 1 hour of forecasts is saved over 4 15-minute resolution events
        n_events_per_horizon = timedelta(hours=1) / config["target"].event_resolution
        n_hourly_horizons = config["max_forecast_horizon"] // n_events_per_horizon
        assert (
            len(forecasts) == n_cycles * n_hourly_horizons * n_events_per_horizon
        ), f"we expect 4 forecasts per horizon for each cycle within the prediction window, and {n_cycles} cycles with each {n_hourly_horizons} hourly horizons"
        assert (
            forecasts.lineage.number_of_belief_times == n_cycles
        ), f"we expect 1 belief time per cycle, and {n_cycles} cycles"
        # todo: source should mention the CustomLGBM model, though
        assert "TrainPredictPipeline" in str(
            forecasts.lineage.sources[0]
        ), "string representation of the Forecaster (DataSource) should mention the used model"
        for regressor in regressors:
            assert (
                f"{regressor.name}_regressor{regressor.id}"
                in forecasts.lineage.sources[0].attributes["data_generator"]["config"][
                    "future_regressors"
                ]
            ), f"data generator config should mention regressor {regressor.name}"
