import pytest

from datetime import datetime, timedelta, timezone

from flexmeasures.data.models.forecasting.pipelines.train_predict import (
    TrainPredictPipeline,
)


@pytest.mark.parametrize(
    ["kwargs", "expected_error"],
    [
        (
            {
                "sensors": {"PV": 313},
                "regressors": ["autoregressive"],
                "target": "PV",
                "model_save_dir": "flexmeasures/data/models/forecasting/artifacts/models",
                "output_path": None,
                "start_date": datetime(
                    2025, 7, 1, 0, 0, tzinfo=timezone(timedelta(seconds=7200))
                ),
                "end_date": datetime(
                    2025, 7, 3, 0, 0, tzinfo=timezone(timedelta(seconds=7200))
                ),
                "train_period_in_hours": 24.0,
                "sensor_to_save": 313,
                "predict_start": datetime(
                    2025, 7, 2, 0, 0, tzinfo=timezone(timedelta(seconds=7200))
                ),
                "predict_period_in_hours": 24,
                "max_forecast_horizon": 24,
                "forecast_frequency": 1,
                "probabilistic": False,
                "as_job": False,
            },
            "Try decreasing the --start-date.",
        )
    ],
)
def test_bad_timing_params(setup_assets, kwargs, expected_error):
    sensor_id = setup_assets["solar-asset-1"].sensors[0].id
    kwargs["sensors"]["PV"] = sensor_id
    as_job = kwargs.pop("as_job")
    with pytest.raises(Exception) as e_info:
        TrainPredictPipeline(**kwargs).run(as_job=as_job)
    assert expected_error in str(e_info)
