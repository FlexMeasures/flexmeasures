from __future__ import annotations

import pytest

import logging

from datetime import timedelta

from marshmallow import ValidationError

from flexmeasures.data.models.forecasting.pipelines import TrainPredictPipeline
from flexmeasures.data.models.forecasting.exceptions import CustomException
from flexmeasures.data.tests.utils import work_on_rq
from flexmeasures.data.services.forecasting import handle_forecasting_exception


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
                "train_period": "P2D",
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
                "as_job": True,
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
            {  # Test: duplicate sensor names in past and future regressors
                "sensor": "solar-sensor",
                "past_regressors": ["irradiance-sensor"],
                "future_regressors": ["irradiance-sensor"],
                "model_save_dir": "flexmeasures/data/models/forecasting/artifacts/models",
                "output_path": None,
                "start_date": "2025-01-01T00:00+02:00",
                "start_predict_date": "2025-01-04T00:00+02:00",
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
                "train_period": "P2D",
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
    app,
    setup_fresh_test_forecast_data,
    config,  # config passed to the Forecaster
    params,  # parameters passed to the compute method of the Forecaster
    expected_error: bool | tuple[type[BaseException], str],
):
    sensor = setup_fresh_test_forecast_data[params["sensor"]]
    params["sensor"] = sensor.id

    past_regressors = [
        setup_fresh_test_forecast_data[regressor_name]
        for regressor_name in params.get("past_regressors", [])
    ]
    future_regressors = [
        setup_fresh_test_forecast_data[regressor_name]
        for regressor_name in params.get("future_regressors", [])
    ]
    regressors = [
        setup_fresh_test_forecast_data[regressor_name]
        for regressor_name in params.get("regressors", [])
    ]

    if params.get("past_regressors"):
        params["past_regressors"] = [regressor.id for regressor in past_regressors]

    if params.get("future_regressors"):
        params["future_regressors"] = [regressor.id for regressor in future_regressors]

    if params.get("regressors"):
        params["regressors"] = [regressor.id for regressor in regressors]

    if expected_error:
        with pytest.raises(expected_error[0]) as e_info:
            pipeline = TrainPredictPipeline(config=config)
            pipeline.compute(parameters=params)
        assert expected_error[1] in str(e_info)
    else:
        pipeline = TrainPredictPipeline(config=config)
        pipeline_returns = pipeline.compute(parameters=params)

        # Check pipeline properties
        for attr in ("model",):
            if config.get(attr):
                assert hasattr(pipeline, attr)

        if params.get("as_job"):
            work_on_rq(
                app.queues["forecasting"], exc_handler=handle_forecasting_exception
            )

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
        data_generator_config = source.attributes["data_generator"]["config"]
        assert data_generator_config["model"] == "CustomLGBM"

        # Check DataGenerator parameters stored under DataSource attributes
        data_generator_params = source.attributes["data_generator"]["parameters"]
        assert (
            "missing_threshold" in data_generator_params
        ), "data generator parameters should mention missing_threshold"
        for regressor in past_regressors:
            assert (
                regressor.id in data_generator_params["past_regressors"]
            ), f"data generator parameters should mention past regressor {regressor.name}"

        for regressor in future_regressors:
            assert (
                regressor.id in data_generator_params["future_regressors"]
            ), f"data generator parameters should mention future regressor {regressor.name}"
        for regressor in regressors:
            assert (
                regressor.id in data_generator_params["past_regressors"]
            ), f"data generator parameters should mention regressor {regressor.name} as a past regressor"
            assert (
                regressor.id in data_generator_params["future_regressors"]
            ), f"data generator parameters should mention regressor {regressor.name} as a future regressor"
        assert (
            "regressors" not in data_generator_params
        ), "(past and future) regressors should be stored under 'past_regressors' and 'future_regressors' instead"


# Test that missing data logging works and raises CustomException when threshold exceeded
@pytest.mark.parametrize(
    ["config", "params"],
    [  # Target sensor has missing data
        (
            {
                # "model": "CustomLGBM",
            },
            {
                "sensor": "solar-sensor",
                "model_save_dir": "flexmeasures/data/models/forecasting/artifacts/models",
                "output_path": None,
                "start_date": "2025-01-01T00:00+02:00",
                "end_date": "2025-01-30T00:00+02:00",
                "sensor_to_save": None,
                "start_predict_date": "2025-01-25T00:00+02:00",
                "retrain_frequency": "P1D",
                "max_forecast_horizon": "PT1H",
                "forecast_frequency": "PT1H",
                "missing_threshold": "0.0",
                "probabilistic": False,
            },
        ),
        # Empty forecasts in sensor passed as future regressor.
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
                "end_date": "2025-01-30T00:00+02:00",
                "missing_threshold": "0.0",
                "sensor_to_save": None,
                "start_predict_date": "2025-01-25T00:00+02:00",
                "retrain_frequency": "P1D",
                "max_forecast_horizon": "PT1H",
                "forecast_frequency": "PT1H",
                "probabilistic": False,
            },
        ),
    ],
)
def test_missing_data_logs_warning(
    setup_fresh_test_forecast_data_with_missing_data,
    config,
    params,
    caplog,
):
    """
    Verify that a CustomException is raised (wrapping a ValueError)
    """
    sensor = setup_fresh_test_forecast_data_with_missing_data[params["sensor"]]
    params["sensor"] = sensor.id

    past_regressors = [
        setup_fresh_test_forecast_data_with_missing_data[reg]
        for reg in params.get("past_regressors", [])
    ]
    future_regressors = [
        setup_fresh_test_forecast_data_with_missing_data[reg]
        for reg in params.get("future_regressors", [])
    ]
    regressors = [
        setup_fresh_test_forecast_data_with_missing_data[reg]
        for reg in params.get("regressors", [])
    ]
    params["missing_threshold"] = float(params.get("missing_threshold"))
    if params.get("past_regressors"):
        params["past_regressors"] = [r.id for r in past_regressors]
    if params.get("future_regressors"):
        params["future_regressors"] = [r.id for r in future_regressors]
    if params.get("regressors"):
        params["regressors"] = [r.id for r in regressors]

    with caplog.at_level(logging.WARNING):
        pipeline = TrainPredictPipeline(config=config)
        # Expect CustomException when missing data exceeds threshold
        with pytest.raises(CustomException) as excinfo:
            pipeline.compute(parameters=params)
        assert "missing values" in str(
            excinfo.value
        ), "Expected CustomException for missing data threshold"


# Test that max_training_period caps train_period and logs a warning
@pytest.mark.parametrize(
    ["config", "params"],
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
                "end_date": "2025-01-30T00:00+02:00",
                "max_training_period": "P10D",  # cap at 10 days
                "sensor_to_save": None,
                "start_predict_date": "2025-01-25T00:00+02:00",
                "retrain_frequency": "P1D",
                "max_forecast_horizon": "PT1H",
                "forecast_frequency": "PT1H",
                "probabilistic": False,
            },
        ),
    ],
)
def test_train_period_capped_logs_warning(
    setup_fresh_test_forecast_data,
    config,  # config passed to the Forecaster
    params,  # parameters passed to the compute method of the Forecaster
    caplog,
):
    """
    Verify that a warning is logged when train_period exceeds max_training_period,
    and that train_period is capped accordingly.
    """
    sensor = setup_fresh_test_forecast_data[params["sensor"]]
    params["sensor"] = sensor.id

    with caplog.at_level(logging.WARNING):
        pipeline = TrainPredictPipeline(config=config)
        pipeline.compute(parameters=params)

    assert any(
        "train-period is greater than max-training-period" in message
        for message in caplog.messages
    ), "Expected warning about capping train_period"

    params_used = pipeline._parameters
    assert params_used["missing_threshold"] == 1
    assert params_used["train_period_in_hours"] == timedelta(days=10) / timedelta(
        hours=1
    ), "train_period_in_hours should be capped to max_training_period"
