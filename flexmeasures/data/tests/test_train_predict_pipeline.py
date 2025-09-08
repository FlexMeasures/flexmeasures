from __future__ import annotations

import pytest

from datetime import timedelta

from marshmallow import ValidationError

from flexmeasures.data.models.forecasting.pipelines import TrainPredictPipeline


@pytest.mark.parametrize(
    ["config", "params", "expected_error"],
    [
        (
            {
                # "model": "CustomLGBM",
            },
            {
                "sensor": "solar-sensor",
                "model_save_dir": "flexmeasures/data/models/forecasting/artifacts/models",
                "output_path": None,
                "start_date": "2025-01-01T00:00+02:00",
                "end_date": "2025-01-03T00:00+02:00",
                "train_period": 2,
                "sensor_to_save": None,
                "start_predict_date": "2025-01-02T00:00+02:00",
                "retrain_frequency": "P0D",  # 0 days is expected to fail
                "max_forecast_horizon": "PT1H",
                "forecast_frequency": "PT1H",
                "probabilistic": False,
            },
            (ValidationError, "retrain-frequency must be greater than 0"),
        ),
        (
            {
                # "model": "CustomLGBM",
            },
            {
                "sensor": "solar-sensor",
                "future_regressors": ["irradiance-sensor"],
                "model_save_dir": "flexmeasures/data/models/forecasting/artifacts/models",
                "output_path": None,
                "start_date": "2025-01-01T00:00+02:00",
                "start_predict_date": "2025-01-08T00:00+02:00",  # start_predict_date coincides with end of available data in sensor
                "end_date": "2025-01-09T00:00+02:00",
                "sensor_to_save": None,
                "max_forecast_horizon": "PT1H",
                "probabilistic": False,
            },
            None,
        ),
        (
            {
                # "model": "CustomLGBM",
            },
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
                "retrain_frequency": "P1D",
                "max_forecast_horizon": "PT1H",
                "forecast_frequency": "PT1H",
                "probabilistic": False,
            },
            None,
        ),
        # (
        #     {},
        #     {
        #         "sensor": "solar-sensor",
        #         "model_save_dir": "flexmeasures/data/models/forecasting/artifacts/models",
        #         "output_path": None,
        #         "start_date": "2025-07-01T00:00+02:00",
        #         "end_date": "2025-07-12T00:00+02:00",
        #         "train_period": 24.0,
        #         "sensor_to_save": 1,
        #         "start_predict_date": "2025-07-11T17:26+02:00",
        #         "retrain_frequency": "PT24H",
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
    config,  # config passed to the Forecaster
    params,  # parameters passed to the compute method of the Forecaster
    expected_error: bool | tuple[type[BaseException], str],
):
    sensor = setup_fresh_test_forecast_data[params["sensor"]]
    params["sensor"] = sensor.id
    regressors = [
        setup_fresh_test_forecast_data[regressor_name]
        for regressor_name in params.get("future_regressors", [])
    ]
    if regressors:
        params["future_regressors"] = [regressor.id for regressor in regressors]
    if expected_error:
        with pytest.raises(expected_error[0]) as e_info:
            pipeline = TrainPredictPipeline(config=config)
            pipeline.compute(parameters=params)
        assert expected_error[1] in str(e_info)
    else:
        pipeline = TrainPredictPipeline(config=config)
        pipeline.compute(parameters=params)

        # Check pipeline properties
        for attr in ("model",):
            if config.get(attr):
                assert hasattr(pipeline, attr)

        forecasts = sensor.search_beliefs(source_types=["forecaster"])
        dg_params = pipeline._parameters  # parameters stored in the data generator
        n_cycles = (dg_params["end_date"] - dg_params["predict_start"]) / (
            dg_params["forecast_frequency"]
        )
        # 1 hour of forecasts is saved over 4 15-minute resolution events
        n_events_per_horizon = timedelta(hours=1) / dg_params["target"].event_resolution
        n_hourly_horizons = dg_params["max_forecast_horizon"] // timedelta(hours=1)
        assert (
            len(forecasts) == n_cycles * n_hourly_horizons * n_events_per_horizon
        ), f"we expect 4 forecasts per horizon for each cycle within the prediction window, and {n_cycles} cycles with each {n_hourly_horizons} hourly horizons"
        assert (
            forecasts.lineage.number_of_belief_times == n_cycles
        ), f"we expect 1 belief time per cycle, and {n_cycles} cycles"
        source = forecasts.lineage.sources[0]
        assert "TrainPredictPipeline" in str(
            source
        ), "string representation of the Forecaster (DataSource) should mention the used model"

        # Check DataGenerator configuration stored under DataSource attributes
        # todo: source should mention the CustomLGBM model, though
        # data_generator_config = source.attributes["data_generator"]["config"]
        # assert data_generator_config["model"] == "CustomLGBM"

        # Check DataGenerator parameters stored under DataSource attributes
        data_generator_params = source.attributes["data_generator"]["parameters"]
        for regressor in regressors:
            assert (
                regressor.id in data_generator_params["future_regressors"]
            ), f"data generator parameters should mention regressor {regressor.name}"
