from __future__ import annotations

import pytest

import logging
import pandas as pd
from datetime import timedelta

from marshmallow import ValidationError

from flexmeasures.data.models.forecasting.exceptions import NotEnoughDataException
from flexmeasures.data.models.forecasting.pipelines import TrainPredictPipeline
from flexmeasures.utils.job_utils import work_on_rq
from flexmeasures.data.services.forecasting import handle_forecasting_exception


@pytest.mark.parametrize(
    ["config", "params", "as_job", "expected_error"],
    [
        (
            {
                # "model": "CustomLGBM",
                "retrain-frequency": "P0D",  # 0 days is expected to fail
            },
            {
                "sensor": "solar-sensor",
                "model-save-dir": "flexmeasures/data/models/forecasting/artifacts/models",
                "output-path": None,
                "start-date": "2025-01-01T00:00+02:00",
                "end-date": "2025-01-03T00:00+02:00",
                "train-period": "P2D",
                "sensor-to-save": None,
                "start-predict-date": "2025-01-02T00:00+02:00",
                "max-forecast-horizon": "PT1H",
                "forecast-frequency": "PT1H",
                "probabilistic": False,
            },
            False,
            (ValidationError, "retrain-frequency must be at least 1 hour"),
        ),
        (
            {
                # "model": "CustomLGBM",
                "future-regressors": ["irradiance-sensor"],
            },
            {
                "sensor": "solar-sensor",
                "model-save-dir": "flexmeasures/data/models/forecasting/artifacts/models",
                "output-path": None,
                "start-date": "2025-01-01T00:00+02:00",
                "start-predict-date": "2025-01-08T00:00+02:00",  # start-predict-date coincides with end of available data in sensor
                "end-date": "2025-01-09T00:00+02:00",
                "sensor-to-save": None,
                "max-forecast-horizon": "PT1H",
                "forecast-frequency": "PT24H",  # 1 cycle and 1 viewpoint
                "probabilistic": False,
            },
            True,
            None,
        ),
        (
            {
                # "model": "CustomLGBM",
                "future-regressors": ["irradiance-sensor"],
            },
            {
                "sensor": "solar-sensor",
                "model-save-dir": "flexmeasures/data/models/forecasting/artifacts/models",
                "output-path": None,
                # "start-date": "2025-01-01T00:00+02:00",  # without a start date, max-training-period takes over
                "max-training-period": "P7D",
                "start-predict-date": "2025-01-08T00:00+02:00",  # start-predict-date coincides with end of available data in sensor
                "end-date": "2025-01-09T00:00+02:00",
                "sensor-to-save": None,
                "max-forecast-horizon": "PT1H",
                "forecast-frequency": "PT24H",  # 1 cycle and 1 viewpoint
                "probabilistic": False,
            },
            False,
            None,
        ),
        (
            {
                # "model": "CustomLGBM",
                "past-regressors": ["irradiance-sensor"],
                "future-regressors": ["irradiance-sensor"],
            },
            {  # Test: duplicate sensor names in past and future regressors
                "sensor": "solar-sensor",
                "model-save-dir": "flexmeasures/data/models/forecasting/artifacts/models",
                "output-path": None,
                "start-date": "2025-01-01T00:00+02:00",
                "start-predict-date": "2025-01-08T00:00+02:00",
                "end-date": "2025-01-09T00:00+02:00",
                "sensor-to-save": None,
                "max-forecast-horizon": "PT1H",
                "forecast-frequency": "PT24H",
                "probabilistic": False,
            },
            False,
            None,
        ),
        (
            {
                # "model": "CustomLGBM",
                "future-regressors": ["irradiance-sensor"],
                "retrain-frequency": "P1D",
            },
            {
                "sensor": "solar-sensor",
                "model-save-dir": "flexmeasures/data/models/forecasting/artifacts/models",
                "output-path": None,
                "start-date": "2025-01-01T00:00+02:00",
                "end-date": "2025-01-03T00:00+02:00",
                "train-period": "P2D",
                "sensor-to-save": None,
                "start-predict-date": "2025-01-02T00:00+02:00",
                "max-forecast-horizon": "PT1H",
                "forecast-frequency": "PT24H",
                "probabilistic": False,
            },
            False,
            None,
        ),
    ],
)
def test_train_predict_pipeline(  # noqa: C901
    app,
    setup_fresh_test_forecast_data,
    config,  # config passed to the Forecaster
    params,  # parameters passed to the compute method of the Forecaster
    as_job: bool,
    expected_error: bool | tuple[type[BaseException], str],
):
    sensor = setup_fresh_test_forecast_data[params["sensor"]]
    params["sensor"] = sensor.id

    past_regressors = [
        setup_fresh_test_forecast_data[regressor_name]
        for regressor_name in config.get("past-regressors", [])
    ]
    future_regressors = [
        setup_fresh_test_forecast_data[regressor_name]
        for regressor_name in config.get("future-regressors", [])
    ]
    regressors = [
        setup_fresh_test_forecast_data[regressor_name]
        for regressor_name in params.get("regressors", [])
    ]

    if config.get("past-regressors"):
        config["past-regressors"] = [regressor.id for regressor in past_regressors]

    if config.get("future-regressors"):
        config["future-regressors"] = [regressor.id for regressor in future_regressors]

    if params.get("regressors"):
        params["regressors"] = [regressor.id for regressor in regressors]

    if expected_error:
        with pytest.raises(expected_error[0]) as e_info:
            pipeline = TrainPredictPipeline(config=config)
            pipeline.compute(parameters=params)
        assert expected_error[1] in str(e_info)
    else:
        pipeline = TrainPredictPipeline(config=config)
        pipeline_returns = pipeline.compute(parameters=params, as_job=as_job)

        # Check pipeline properties
        for attr in ("model",):
            if config.get(attr):
                assert hasattr(pipeline, attr)

        if as_job:
            work_on_rq(
                app.queues["forecasting"], exc_handler=handle_forecasting_exception
            )

        forecasts = sensor.search_beliefs(source_types=["forecaster"])
        dg_params = pipeline._parameters  # parameters stored in the data generator
        m_viewpoints = (dg_params["end_date"] - dg_params["predict_start"]) / (
            dg_params["forecast_frequency"]
        )
        # 1 hour of forecasts is saved over 4 15-minute resolution events
        n_events_per_horizon = timedelta(hours=1) / dg_params["sensor"].event_resolution
        n_hourly_horizons = dg_params["max_forecast_horizon"] // timedelta(hours=1)
        assert (
            len(forecasts) == m_viewpoints * n_hourly_horizons * n_events_per_horizon
        ), f"we expect 4 forecasts per horizon for each viewpoint within the prediction window, and {m_viewpoints} viewpoints with each {n_hourly_horizons} hourly horizons"
        assert (
            forecasts.lineage.number_of_belief_times == m_viewpoints
        ), f"we expect {m_viewpoints} viewpoints"
        source = forecasts.lineage.sources[0]
        assert "TrainPredictPipeline" in str(
            source
        ), "string representation of the Forecaster (DataSource) should mention the used model"

        if as_job:
            # Fetch returned job
            job = app.queues["forecasting"].fetch_job(pipeline_returns)

            assert (
                job is not None
            ), "a returned job should exist in the forecasting queue"

            if job.dependency_ids:
                cycle_job_ids = [job]  # only one cycle job, no wrap-up job
            else:
                cycle_job_ids = job.kwargs.get("cycle_job_ids", [])  # wrap-up job case

            finished_jobs = app.queues["forecasting"].finished_job_registry

            for job_id in cycle_job_ids:
                job = app.queues["forecasting"].fetch_job(job_id)
                assert job is not None, f"Job {job_id} should exist"
                assert (
                    job_id in finished_jobs
                ), f"Job {job_id} should be in the finished registry"

        else:
            # Sync case: pipeline returns a non-empty list
            assert (
                isinstance(pipeline_returns, list) and len(pipeline_returns) > 0
            ), "pipeline should return a non-empty list"
            assert all(
                isinstance(item, dict) for item in pipeline_returns
            ), "each item should be a dict"

            for pipeline_return in pipeline_returns:
                assert {"data", "sensor"}.issubset(
                    pipeline_return.keys()
                ), "returned dict should have data and sensor keys"
                assert (
                    pipeline_return["sensor"].id == dg_params["sensor_to_save"].id
                ), "returned sensor should match sensor that forecasts will be saved into"
                pd.testing.assert_frame_equal(
                    forecasts.sort_index(),
                    pipeline_return["data"].sort_index(),
                )

        # Check DataGenerator configuration stored under DataSource attributes
        data_generator_config = source.attributes["data_generator"]["config"]
        assert data_generator_config["model"] == "CustomLGBM"
        assert (
            "missing-threshold" in data_generator_config
        ), "data generator config should mention missing_threshold"
        for regressor in past_regressors:
            assert (
                regressor.id in data_generator_config["past-regressors"]
            ), f"data generator config should mention past regressor {regressor.name}"

        for regressor in future_regressors:
            assert (
                regressor.id in data_generator_config["future-regressors"]
            ), f"data generator config should mention future regressor {regressor.name}"
        for regressor in regressors:
            assert (
                regressor.id in data_generator_config["past-regressors"]
            ), f"data generator config should mention regressor {regressor.name} as a past regressor"
            assert (
                regressor.id in data_generator_config["future-regressors"]
            ), f"data generator config should mention regressor {regressor.name} as a future regressor"
        assert (
            "regressors" not in data_generator_config
        ), "(past and future) regressors should be stored under 'past_regressors' and 'future_regressors' instead"

        # Check DataGenerator parameters stored under DataSource attributes is empty
        data_generator_params = source.attributes["data_generator"]["parameters"]
        # todo: replace this with `assert data_generator_params == {}` after moving max-training-period to config
        assert "max-training-period" in data_generator_params


# Test that missing data logging works and raises NotEnoughDataException when threshold exceeded
@pytest.mark.parametrize(
    ["config", "params"],
    [  # Target sensor has missing data
        (
            {
                # "model": "CustomLGBM",
                "missing-threshold": "0.0",
            },
            {
                "sensor": "solar-sensor",
                "model-save-dir": "flexmeasures/data/models/forecasting/artifacts/models",
                "output-path": None,
                "start-date": "2025-01-01T00:00+02:00",
                "end-date": "2025-01-30T00:00+02:00",
                "sensor-to-save": None,
                "start-predict-date": "2025-01-25T00:00+02:00",
                "retrain-frequency": "P1D",
                "max-forecast-horizon": "PT1H",
                "forecast-frequency": "PT1H",
                "probabilistic": False,
            },
        ),
        # Empty forecasts in sensor passed as future regressor.
        (
            {
                # "model": "CustomLGBM",
                "future-regressors": ["irradiance-sensor"],
                "missing-threshold": "0.0",
            },
            {
                "sensor": "solar-sensor",
                "model-save-dir": "flexmeasures/data/models/forecasting/artifacts/models",
                "output-path": None,
                "start-date": "2025-01-01T00:00+02:00",
                "end-date": "2025-01-30T00:00+02:00",
                "sensor-to-save": None,
                "start-predict-date": "2025-01-25T00:00+02:00",
                "retrain-frequency": "P1D",
                "max-forecast-horizon": "PT1H",
                "forecast-frequency": "PT1H",
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
    Verify that a NotEnoughDataException is raised (wrapping a ValueError)
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
    config["missing-threshold"] = float(config.get("missing-threshold"))
    if config.get("past-regressors"):
        config["past-regressors"] = [r.id for r in past_regressors]
    if config.get("future-regressors"):
        config["future-regressors"] = [r.id for r in future_regressors]
    if params.get("regressors"):
        params["regressors"] = [r.id for r in regressors]

    pipeline = TrainPredictPipeline(config=config)
    # Expect ValueError when missing data exceeds threshold
    with pytest.raises(NotEnoughDataException) as excinfo:
        pipeline.compute(parameters=params)
    assert "missing values" in str(
        excinfo.value
    ), "Expected NotEnoughDataException for missing data threshold"


# Test that max_training-period caps train-period and logs a warning
@pytest.mark.parametrize(
    ["config", "params"],
    [
        (
            {
                # "model": "CustomLGBM",
            },
            {
                "sensor": "solar-sensor",
                "model-save-dir": "flexmeasures/data/models/forecasting/artifacts/models",
                "output-path": None,
                "start-date": "2025-01-01T00:00+02:00",
                "end-date": "2025-01-30T00:00+02:00",
                "max-training-period": "P10D",  # cap at 10 days
                "sensor-to-save": None,
                "start-predict-date": "2025-01-25T00:00+02:00",
                "retrain-frequency": "P1D",
                "max-forecast-horizon": "PT1H",
                "forecast-frequency": "PT1H",
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
    Verify that a warning is logged when train-period exceeds max-training-period,
    and that train-period is capped accordingly.
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
    config_used = pipeline._config
    assert config_used["missing_threshold"] == 1
    assert params_used["train_period_in_hours"] == timedelta(days=10) / timedelta(
        hours=1
    ), "train_period_in_hours should be capped to max_training_period"
