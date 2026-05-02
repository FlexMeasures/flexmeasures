from __future__ import annotations

import pytest

import logging
import pandas as pd
from datetime import datetime, timedelta

from marshmallow import ValidationError

from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.forecasting.exceptions import NotEnoughDataException
from flexmeasures.data.models.forecasting.pipelines.base import BasePipeline
from flexmeasures.data.models.generic_assets import (
    GenericAsset as Asset,
    GenericAssetType,
)
from flexmeasures.data.models.forecasting.pipelines import TrainPredictPipeline
from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.utils.job_utils import work_on_rq
from flexmeasures.data.services.forecasting import handle_forecasting_exception


@pytest.mark.parametrize(
    ["config", "params", "as_job", "expected_error"],
    [
        (
            {
                # "model": "CustomLGBM",
                "train-start": "2025-01-01T00:00+02:00",
                "train-period": "P2D",
                "retrain-frequency": "P0D",  # 0 days is expected to fail
            },
            {
                "sensor": "solar-sensor",
                "model-save-dir": "flexmeasures/data/models/forecasting/artifacts/models",
                "output-path": None,
                "end": "2025-01-03T00:00+02:00",
                "sensor-to-save": None,
                "start": "2025-01-02T00:00+02:00",
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
                "train-start": "2025-01-01T00:00+02:00",
            },
            {
                "sensor": "solar-sensor",
                "model-save-dir": "flexmeasures/data/models/forecasting/artifacts/models",
                "output-path": None,
                "start": "2025-01-08T00:00+02:00",  # start coincides with end of available data in sensor
                "end": "2025-01-09T00:00+02:00",
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
                "train-start": "2025-01-01T00:00+02:00",
                "retrain-frequency": "PT12H",
            },
            {
                "sensor": "solar-sensor",
                "model-save-dir": "flexmeasures/data/models/forecasting/artifacts/models",
                "output-path": None,
                "start": "2025-01-08T00:00+02:00",  # start coincides with end of available data in sensor
                "end": "2025-01-09T00:00+02:00",
                "sensor-to-save": None,
                "max-forecast-horizon": "PT1H",
                "forecast-frequency": "PT12H",  # 2 cycles and 2 viewpoints
                "probabilistic": False,
            },
            True,
            None,
        ),
        (
            {
                # "model": "CustomLGBM",
                "future-regressors": ["irradiance-sensor"],
                # "train-start": "2025-01-01T00:00+02:00",  # without a start date, max-training-period takes over
                "max-training-period": "P7D",
            },
            {
                "sensor": "solar-sensor",
                "model-save-dir": "flexmeasures/data/models/forecasting/artifacts/models",
                "output-path": None,
                "start": "2025-01-08T00:00+02:00",  # start coincides with end of available data in sensor
                "end": "2025-01-09T00:00+02:00",
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
                "train-start": "2025-01-01T00:00+02:00",
            },
            {  # Test: duplicate sensor names in past and future regressors
                "sensor": "solar-sensor",
                "model-save-dir": "flexmeasures/data/models/forecasting/artifacts/models",
                "output-path": None,
                "start": "2025-01-08T00:00+02:00",
                "end": "2025-01-09T00:00+02:00",
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
                "future-regressors": ["irradiance-sensor", "solar-sensor-1"],
                "train-start": "2025-01-01T00:00+02:00",
            },
            {
                "sensor": "solar-sensor",
                "model-save-dir": "flexmeasures/data/models/forecasting/artifacts/models",
                "output-path": None,
                "start": "2025-01-08T00:00+02:00",
                "end": "2025-01-09T00:00+02:00",
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
                "past-regressors": ["irradiance-sensor", "solar-sensor-1"],
                "train-start": "2025-01-01T00:00+02:00",
            },
            {
                "sensor": "solar-sensor",
                "model-save-dir": "flexmeasures/data/models/forecasting/artifacts/models",
                "output-path": None,
                "start": "2025-01-08T00:00+02:00",
                "end": "2025-01-09T00:00+02:00",
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
                "regressors": ["irradiance-sensor", "solar-sensor-1"],
                "train-start": "2025-01-01T00:00+02:00",
            },
            {
                "sensor": "solar-sensor",
                "model-save-dir": "flexmeasures/data/models/forecasting/artifacts/models",
                "output-path": None,
                "start": "2025-01-08T00:00+02:00",
                "end": "2025-01-09T00:00+02:00",
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
                "train-start": "2025-01-01T00:00+02:00",
                "train-period": "P2D",
            },
            {
                "sensor": "solar-sensor",
                "model-save-dir": "flexmeasures/data/models/forecasting/artifacts/models",
                "output-path": None,
                "end": "2025-01-03T00:00+02:00",
                "sensor-to-save": None,
                "start": "2025-01-02T00:00+02:00",
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
    config_regressors = [
        setup_fresh_test_forecast_data[regressor_name]
        for regressor_name in config.get("regressors", [])
    ]
    regressors = [
        setup_fresh_test_forecast_data[regressor_name]
        for regressor_name in params.get("regressors", [])
    ]

    if config.get("past-regressors"):
        config["past-regressors"] = [regressor.id for regressor in past_regressors]

    if config.get("future-regressors"):
        config["future-regressors"] = [regressor.id for regressor in future_regressors]

    if config.get("regressors"):
        config["regressors"] = [regressor.id for regressor in config_regressors]

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

            # Fetch returned job
            job = app.queues["forecasting"].fetch_job(pipeline_returns["job_id"])

            assert (
                job is not None
            ), "a returned job should exist in the forecasting queue"

            if not job.dependency_ids:
                cycle_job_ids = [job.id]  # only one cycle job, no wrap-up job
            else:
                assert (
                    job.is_finished
                ), f"The wrap-up job should be finished, and not {job.get_status()}"
                cycle_job_ids = job.kwargs.get("cycle_job_ids", [])  # wrap-up job case

            finished_jobs = app.queues["forecasting"].finished_job_registry

            for job_id in cycle_job_ids:
                job = app.queues["forecasting"].fetch_job(job_id)
                assert job is not None, f"Job {job_id} should exist"
                assert (
                    job_id in finished_jobs
                ), f"Job {job_id} should be in the finished registry"

        forecasts = sensor.search_beliefs(
            source_types=["forecaster"], most_recent_beliefs_only=False
        )

        dg_params = pipeline._parameters  # parameters stored in the data generator
        m_viewpoints = (dg_params["end_date"] - dg_params["predict_start"]) / (
            dg_params["forecast_frequency"]
        )
        # 1 hour of forecasts is saved over 4 15-minute resolution events
        n_events_per_horizon = timedelta(hours=1) / dg_params["sensor"].event_resolution
        n_hourly_horizons = dg_params["max_forecast_horizon"] // timedelta(hours=1)
        n_cycles = max(
            timedelta(hours=dg_params["predict_period_in_hours"])
            // max(
                pipeline._config["retrain_frequency"],
                pipeline._parameters["forecast_frequency"],
            ),
            1,
        )
        assert (
            len(forecasts)
            == m_viewpoints * n_hourly_horizons * n_events_per_horizon * n_cycles
        ), (
            f"we expect {n_events_per_horizon} event(s) per horizon, "
            f"{n_hourly_horizons} horizon(s), {m_viewpoints} viewpoint(s)"
            f"{f', and {n_cycles} cycle(s)' if n_cycles > 1 else ''}"
        )
        assert (
            forecasts.lineage.number_of_belief_times == m_viewpoints
        ), f"we expect {m_viewpoints} viewpoints"
        source = forecasts.lineage.sources[0]
        assert "TrainPredictPipeline" in str(
            source
        ), "string representation of the Forecaster (DataSource) should mention the used model"

        if not as_job:
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
        assert "max-training-period" in data_generator_config

        # Check DataGenerator parameters stored under DataSource attributes is empty
        assert "parameters" not in source.attributes["data_generator"]


# Test that missing data logging works and raises NotEnoughDataException when threshold exceeded
@pytest.mark.parametrize(
    ["config", "params"],
    [  # Target sensor has missing data
        (
            {
                # "model": "CustomLGBM",
                "missing-threshold": "0.0",
                "train-start": "2025-01-01T00:00+02:00",
            },
            {
                "sensor": "solar-sensor",
                "model-save-dir": "flexmeasures/data/models/forecasting/artifacts/models",
                "output-path": None,
                "end": "2025-01-30T00:00+02:00",
                "sensor-to-save": None,
                "start": "2025-01-25T00:00+02:00",
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
                "train-start": "2025-01-01T00:00+02:00",
            },
            {
                "sensor": "solar-sensor",
                "model-save-dir": "flexmeasures/data/models/forecasting/artifacts/models",
                "output-path": None,
                "end": "2025-01-30T00:00+02:00",
                "sensor-to-save": None,
                "start": "2025-01-25T00:00+02:00",
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
                "retrain-frequency": "P1D",
                "train-start": "2025-01-01T00:00+02:00",
                "max-training-period": "P10D",  # cap at 10 days
            },
            {
                "sensor": "solar-sensor",
                "model-save-dir": "flexmeasures/data/models/forecasting/artifacts/models",
                "output-path": None,
                "end": "2025-01-30T00:00+02:00",
                "sensor-to-save": None,
                "start": "2025-01-25T00:00+02:00",
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

    config_used = pipeline._config
    assert config_used["missing_threshold"] == 1
    assert config_used["train_period_in_hours"] == timedelta(days=10) / timedelta(
        hours=1
    ), "train_period_in_hours should be capped to max_training_period"


def test_prior_restricts_training_beliefs(
    app,
    setup_fresh_test_forecast_data_with_anomalous_beliefs,
):
    """
    Verify that the 'prior' parameter restricts which beliefs are used by the forecasting pipeline.

    The fixture provides a sensor with two sets of beliefs for Jan 1–7 2025:
    - Phase 1 (normal): value = 50 kW, recorded on Dec 31, 2024
    - Phase 2 (anomalous): value = 5000 kW, recorded on Jan 10, 2025

    When 'prior' is set before Jan 10, only Phase 1 beliefs are available,
    so the model is trained on normal values and produces low forecasts.
    When 'prior' is set after Jan 10, Phase 2 beliefs become the most recent
    per event, so the model is trained on anomalous values and produces high forecasts.
    """
    sensor = setup_fresh_test_forecast_data_with_anomalous_beliefs["anomaly-sensor"]

    normal_value = 50.0
    anomalous_value = 5000.0

    base_config = {
        "train-start": "2025-01-01T00:00+00:00",
    }
    base_params = {
        "sensor": sensor.id,
        "model-save-dir": "flexmeasures/data/models/forecasting/artifacts/models",
        "output-path": None,
        "start": "2025-01-08T00:00+00:00",
        "end": "2025-01-09T00:00+00:00",
        "sensor-to-save": None,
        "max-forecast-horizon": "PT1H",
        "forecast-frequency": "PT1H",
        "probabilistic": False,
    }

    # Run with prior before the anomalous beliefs (Jan 10) → only normal values used
    params_before_anomaly = {
        **base_params,
        "prior": "2025-01-05T00:00+00:00",  # before late_belief_time (Jan 10)
    }
    pipeline_before = TrainPredictPipeline(config=base_config)
    returns_before = pipeline_before.compute(parameters=params_before_anomaly)
    forecasts_before = returns_before[0]["data"]

    # Run with prior after the anomalous beliefs (Jan 10) → anomalous values used
    params_after_anomaly = {
        **base_params,
        "prior": "2025-01-15T00:00+00:00",  # after late_belief_time (Jan 10)
    }
    pipeline_after = TrainPredictPipeline(config=base_config)
    returns_after = pipeline_after.compute(parameters=params_after_anomaly)
    forecasts_after = returns_after[0]["data"]

    mean_before = float(forecasts_before["event_value"].mean())
    mean_after = float(forecasts_after["event_value"].mean())

    # When prior is before the anomaly, forecasts should reflect normal values (close to 50)
    assert mean_before < anomalous_value / 2, (
        f"Forecasts with prior before anomaly should be well below {anomalous_value / 2}, "
        f"but mean was {mean_before:.1f}"
    )

    # When prior is after the anomaly, forecasts should reflect anomalous values (close to 5000)
    assert mean_after > normal_value * 5, (
        f"Forecasts with prior after anomaly should be well above {normal_value * 5}, "
        f"but mean was {mean_after:.1f}"
    )

    # The two runs must produce meaningfully different forecasts
    assert mean_after > mean_before * 10, (
        f"Forecasts after anomaly ({mean_after:.1f}) should be at least 10x higher "
        f"than forecasts before anomaly ({mean_before:.1f})"
    )


def test_future_regressor_splits_use_only_beliefs_known_at_issue_time(monkeypatch):
    target_sensor = type(
        "SensorStub",
        (),
        {"name": "target", "id": 1, "event_resolution": timedelta(hours=1)},
    )()
    future_regressor = type(
        "SensorStub",
        (),
        {"name": "weather", "id": 2, "event_resolution": timedelta(hours=1)},
    )()

    pipeline = BasePipeline(
        target_sensor=target_sensor,
        future_regressors=[future_regressor],
        past_regressors=[],
        n_steps_to_predict=1,
        max_forecast_horizon=1,
        forecast_frequency=1,
        event_starts_after=datetime(2025, 1, 7, 23),
        event_ends_before=datetime(2025, 1, 8, 1),
        predict_start=datetime(2025, 1, 8),
        predict_end=datetime(2025, 1, 8, 1),
    )
    issue_time = pd.Timestamp("2025-01-08T00:00:00")
    future_col = pipeline.future_regressors[0]

    df = pd.DataFrame(
        [
            {
                "event_start": pd.Timestamp("2025-01-07T23:00:00"),
                "belief_time": issue_time - pd.Timedelta(hours=2),
                pipeline.target: None,
                future_col: 88.0,
            },
            {
                "event_start": pd.Timestamp("2025-01-07T23:00:00"),
                "belief_time": issue_time,
                pipeline.target: 1.0,
                future_col: 10.0,
            },
            {
                "event_start": pd.Timestamp("2025-01-08T00:00:00"),
                "belief_time": issue_time - pd.Timedelta(minutes=5),
                pipeline.target: None,
                future_col: 20.0,
            },
            {
                "event_start": pd.Timestamp("2025-01-08T00:00:00"),
                "belief_time": issue_time + pd.Timedelta(minutes=5),
                pipeline.target: None,
                future_col: 99.0,
            },
            {
                "event_start": pd.Timestamp("2025-01-08T01:00:00"),
                "belief_time": issue_time,
                pipeline.target: None,
                future_col: 30.0,
            },
        ]
    )

    captured_future_frames = []

    def capture_frame(self, df, sensors, sensor_names, start, end, **kwargs):
        if sensor_names == self.future_regressors:
            captured_future_frames.append(df.copy())
        return df

    monkeypatch.setattr(BasePipeline, "detect_and_fill_missing_values", capture_frame)

    pipeline.split_data_all_beliefs(df, is_predict_pipeline=True)

    assert len(captured_future_frames) == 1
    values_by_event = captured_future_frames[0].set_index("event_start")[future_col]
    assert values_by_event.loc[pd.Timestamp("2025-01-07T23:00:00")] == 10.0
    assert values_by_event.loc[pd.Timestamp("2025-01-08T00:00:00")] == 20.0
    assert values_by_event.loc[pd.Timestamp("2025-01-08T01:00:00")] == 30.0
    assert 88.0 not in set(values_by_event)
    assert 99.0 not in set(values_by_event)


def test_future_regressor_changes_forecasts_in_issue_time_window(
    app, fresh_db, tmp_path
):
    """
    Integration check for deterministic regressor behavior around issue-time splitting.

    We build two target sensors with identical history, run one with a future regressor
    and one without, and assert the forecast window output differs.
    """
    db = fresh_db

    asset_type = GenericAssetType(name="deterministic-regressor-asset-type")
    asset = Asset(
        name="Deterministic regressor test asset",
        generic_asset_type=asset_type,
        latitude=1.0,
        longitude=1.0,
    )
    source_actual = DataSource(name="deterministic-regressor-actual", type="test")
    source_forecaster = DataSource(name="deterministic-regressor-forecast", type="test")
    db.session.add_all([asset_type, asset, source_actual, source_forecaster])
    db.session.flush()

    target_without_regressor = Sensor(
        name="target-without-regressor",
        generic_asset=asset,
        unit="kW",
        event_resolution=timedelta(hours=1),
    )
    target_with_regressor = Sensor(
        name="target-with-regressor",
        generic_asset=asset,
        unit="kW",
        event_resolution=timedelta(hours=1),
    )
    weather_regressor = Sensor(
        name="weather-regressor",
        generic_asset=asset,
        unit="kW",
        event_resolution=timedelta(hours=1),
    )
    db.session.add_all(
        [target_without_regressor, target_with_regressor, weather_regressor]
    )
    db.session.flush()

    history_index = pd.date_range(
        datetime(2025, 1, 1),
        datetime(2025, 1, 7, 23, 0),
        freq="1h",
        tz="UTC",
    )
    forecast_index = pd.date_range(
        datetime(2025, 1, 8),
        datetime(2025, 1, 8, 23, 0),
        freq="1h",
        tz="UTC",
    )

    # Deterministic but non-periodic-enough pattern so autoregressive-only models
    # cannot trivially extrapolate future behavior from target history alone.
    historical_regressor_values = [
        ((37 * i + 13) % 97) + ((i % 5) * 0.1) for i in range(len(history_index))
    ]
    future_regressor_values = [
        ((53 * i + 7) % 101) + 150 + ((i % 7) * 0.1) for i in range(len(forecast_index))
    ]
    target_historical_values = [3 * value + 5 for value in historical_regressor_values]
    target_future_truth = [3 * value + 5 for value in future_regressor_values]

    beliefs = []
    for ts, reg_value, target_value in zip(
        history_index,
        historical_regressor_values,
        target_historical_values,
    ):
        beliefs.extend(
            [
                TimedBelief(
                    sensor=weather_regressor,
                    event_start=ts,
                    event_value=reg_value,
                    source=source_actual,
                    belief_horizon=timedelta(0),
                ),
                TimedBelief(
                    sensor=target_with_regressor,
                    event_start=ts,
                    event_value=target_value,
                    source=source_actual,
                    belief_horizon=timedelta(0),
                ),
                TimedBelief(
                    sensor=target_without_regressor,
                    event_start=ts,
                    event_value=target_value,
                    source=source_actual,
                    belief_horizon=timedelta(0),
                ),
            ]
        )

    for ts, reg_value in zip(forecast_index, future_regressor_values):
        # Keep a very short horizon for future regressors; this used to be
        # vulnerable to stricter horizon filtering around issue time.
        beliefs.append(
            TimedBelief(
                sensor=weather_regressor,
                event_start=ts,
                event_value=reg_value,
                source=source_forecaster,
                belief_time=ts - timedelta(minutes=5),
            )
        )

    db.session.add_all(beliefs)
    db.session.commit()

    base_config = {"train-start": "2025-01-01T00:00+00:00"}
    common_params = {
        "model-save-dir": str(tmp_path / "models"),
        "output-path": None,
        "start": "2025-01-08T00:00+00:00",
        "end": "2025-01-09T00:00+00:00",
        "sensor-to-save": None,
        "max-forecast-horizon": "PT1H",
        "forecast-frequency": "PT1H",
        "probabilistic": False,
    }

    pipeline_without_regressor = TrainPredictPipeline(config=base_config)
    returns_without_regressor = pipeline_without_regressor.compute(
        parameters={
            **common_params,
            "sensor": target_without_regressor.id,
        }
    )

    pipeline_with_regressor = TrainPredictPipeline(
        config={
            **base_config,
            "future-regressors": [weather_regressor.id],
        }
    )
    returns_with_regressor = pipeline_with_regressor.compute(
        parameters={
            **common_params,
            "sensor": target_with_regressor.id,
        }
    )

    def collapse_to_event_start_series(forecast_df, series_name: str) -> pd.Series:
        """Align forecasts across runs by event_start only.

        BeliefsDataFrame indexes include run-specific belief metadata (e.g. source),
        so joining on the full index can produce empty intersections even when both
        runs contain forecasts for the same event starts.
        """
        series = forecast_df["event_value"].sort_index()
        if not isinstance(series.index, pd.MultiIndex):
            series.index = pd.to_datetime(series.index, utc=True)
            return series.sort_index().rename(series_name)

        assert (
            "event_start" in series.index.names
        ), "Expected event_start in forecast index for deterministic alignment."
        values_by_event = series.rename("event_value").reset_index()
        sort_cols = ["event_start"]
        if "belief_time" in values_by_event.columns:
            sort_cols.append("belief_time")
        values_by_event = values_by_event.sort_values(sort_cols)
        unique_values_per_event = values_by_event.groupby("event_start")[
            "event_value"
        ].nunique()
        assert (unique_values_per_event <= 1).all(), (
            "Expected at most one unique forecast value per event_start. "
            "Conflicting duplicates indicate a forecasting regression."
        )
        values_by_event = values_by_event.drop_duplicates(
            subset=["event_start"], keep="last"
        )
        collapsed_series = values_by_event.set_index("event_start")["event_value"]
        collapsed_series.index = pd.to_datetime(collapsed_series.index, utc=True)
        return collapsed_series.sort_index().rename(series_name)

    forecasts_without_regressor = collapse_to_event_start_series(
        returns_without_regressor[0]["data"], "without_regressor"
    )
    forecasts_with_regressor = collapse_to_event_start_series(
        returns_with_regressor[0]["data"], "with_regressor"
    )
    aligned_forecasts = pd.concat(
        [forecasts_without_regressor, forecasts_with_regressor],
        axis=1,
        join="inner",
    )

    assert list(forecasts_without_regressor.index) == list(forecast_index)
    assert list(forecasts_with_regressor.index) == list(forecast_index)
    assert not aligned_forecasts.empty
    assert aligned_forecasts.notna().all(axis=None)
    assert (
        aligned_forecasts["without_regressor"]
        .ne(aligned_forecasts["with_regressor"])
        .any()
    ), "Forecasts should differ for at least one timestamp when a future regressor is used."

    truth = pd.Series(target_future_truth, index=forecast_index, name="truth")
    mae_without_regressor = (
        aligned_forecasts["without_regressor"]
        .reindex(truth.index)
        .sub(truth)
        .abs()
        .mean()
    )
    mae_with_regressor = (
        aligned_forecasts["with_regressor"].reindex(truth.index).sub(truth).abs().mean()
    )
    first_forecast_timestamp = forecast_index[0]
    first_error_without_regressor = abs(
        aligned_forecasts.loc[first_forecast_timestamp, "without_regressor"]
        - truth.loc[first_forecast_timestamp]
    )
    first_error_with_regressor = abs(
        aligned_forecasts.loc[first_forecast_timestamp, "with_regressor"]
        - truth.loc[first_forecast_timestamp]
    )
    assert (
        first_error_with_regressor < first_error_without_regressor
    ), "At the issue-time boundary, the future-regressor run should be more accurate."
    assert mae_with_regressor < mae_without_regressor, (
        "The future-regressor forecast is expected to be more accurate "
        "on this deterministic synthetic dataset."
    )
