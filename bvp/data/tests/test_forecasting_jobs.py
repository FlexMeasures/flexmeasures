from typing import List
from datetime import datetime, timedelta

import pytz
import pytest
import numpy as np

from bvp.data.models.forecasting.jobs import ForecastingJob
from bvp.data.models.data_sources import DataSource
from bvp.data.models.assets import AssetType, Asset, Power
from bvp.data.models.task_runs import LatestTaskRun
from bvp.data.scripts.make_forecasts import run_forecasting_jobs, data_source_label
from bvp.utils.time_utils import as_bvp_time, bvp_now


@pytest.fixture(scope="function", autouse=True)
def remove_seasonality_for_power_forecasts(db):
    """Make sure the AssetType specs make us query only data we actually have in the test db"""
    asset_types = AssetType.query.all()
    for a in asset_types:
        a.daily_seasonality = False
        a.weekly_seasonality = False
        a.yearly_seasonality = False


def test_running_one_forecasting_job(db):
    """Test one clean run of one job:
    - data source was made,
    - one job should be gone from the list
    - forecasts have been made
    """
    initial_amount_of_jobs = ForecastingJob.query.count()
    assert LatestTaskRun.query.one_or_none() is None
    assert (
        DataSource.query.filter(DataSource.label == data_source_label).one_or_none()
        is None
    )

    run_forecasting_jobs(
        max_forecasts=10,
        # little training as we have little data, turn off transformations until they let this test run (TODO)
        custom_model_params=dict(
            training_and_testing_period=timedelta(hours=2),
            outcome_var_transformation=None,
            regressor_transformation={},
        ),
    )

    data_source = DataSource.query.filter(
        DataSource.label == data_source_label
    ).one_or_none()
    assert data_source is not None

    ltr = LatestTaskRun.query.one_or_none()
    assert ltr.name == "run_forecasting_jobs"
    assert ltr.status is True
    assert ltr.datetime > datetime.utcnow().replace(tzinfo=pytz.utc) - timedelta(
        minutes=2
    )

    assert ForecastingJob.query.count() == initial_amount_of_jobs - 1

    check_forecasts([1])


def test_in_progress_handling(db):
    """ first edit the in_progress_since value of two jobs - one value older than an hour, one 10 minutes old.
        -> The task re-opens the former and runs it. The latter is not touched. The third remaining one is run.
    """
    wind1: Asset = Asset.query.filter_by(name="wind-asset-1").one_or_none()
    old_job: ForecastingJob = ForecastingJob.query.filter_by(
        asset_id=wind1.id
    ).one_or_none()
    old_job.in_progress_since = bvp_now() - timedelta(hours=3)

    wind2: Asset = Asset.query.filter_by(name="wind-asset-2").one_or_none()
    running_job: ForecastingJob = ForecastingJob.query.filter_by(
        asset_id=wind2.id
    ).one_or_none()
    running_job.in_progress_since = bvp_now() - timedelta(minutes=10)
    running_job_id = running_job.id

    run_forecasting_jobs(
        max_forecasts=12,  # take care that we are not selecting the fourth and fifth, invalid jobs
        custom_model_params=dict(
            training_and_testing_period=timedelta(hours=2),
            outcome_var_transformation=None,
            regressor_transformation={},
        ),
    )

    # checking if some jobs were left alone
    left_jobs = ForecastingJob.query.all()
    assert (
        len(left_jobs) == 3
    )  # 1 left alone, two invalid we did not select (see above)
    assert running_job_id in [job.id for job in left_jobs]

    # checking if the right forecasts were made
    assert check_forecasts([1, 3])


def test_forecasting_failures(db):
    """When we include the last two jobs with an invalid range and horizon,
    the three valid ones should still get done.
    The data from the other two should not exist.
    One of them should be deleted, as it was valid, but there was not enough data.
    """
    run_forecasting_jobs(
        max_forecasts=100,  # including the last, failing one
        custom_model_params=dict(
            training_and_testing_period=timedelta(hours=2),
            outcome_var_transformation=None,
            regressor_transformation={},
        ),
    )

    # check if the valid jobs ran, but no other forecasts were made.
    assert ForecastingJob.query.count() == 1
    assert "18 minutes" in str(ForecastingJob.query.one_or_none())
    assert check_forecasts([1, 2, 3])

    # however, the last task run is recorded (as failed)
    ltr = LatestTaskRun.query.one_or_none()
    assert ltr.name == "run_forecasting_jobs"
    assert ltr.status is False
    assert ltr.datetime > datetime.utcnow().replace(tzinfo=pytz.utc) - timedelta(
        minutes=2
    )


def check_forecasts(job_ids: List[int]):
    """
    Check if the expected forecasts were made. Pass in forecast job IDs (see conftest) of jobs you expet to have run.
    :return:
    """
    overall_expected = 0

    wind1: Asset = Asset.query.filter_by(name="wind-asset-1").one_or_none()
    forecasts = (
        Power.query.filter(Power.asset_id == wind1.id)
        .filter(Power.horizon == timedelta(minutes=15))
        .filter(
            (Power.datetime >= as_bvp_time(datetime(2015, 1, 1, 6)))
            & (Power.datetime < as_bvp_time(datetime(2015, 1, 1, 7)))
        )
        .all()
    )
    if 1 in job_ids:
        assert len(forecasts) == 4
        overall_expected += 4
    else:
        assert len(forecasts) == 0

    wind2: Asset = Asset.query.filter_by(name="wind-asset-2").one_or_none()
    forecasts = (
        Power.query.filter(Power.asset_id == wind2.id)
        .filter(Power.horizon == timedelta(minutes=15))
        .filter(
            (Power.datetime >= as_bvp_time(datetime(2015, 1, 1, 14)))
            & (Power.datetime < as_bvp_time(datetime(2015, 1, 1, 17)))
        )
        .all()
    )
    if 2 in job_ids:
        assert len(forecasts) == 12
        overall_expected += 12
    else:
        assert len(forecasts) == 0

    solar1: Asset = Asset.query.filter_by(name="solar-asset-1").one_or_none()
    forecasts = (
        Power.query.filter(Power.asset_id == solar1.id)
        .filter(Power.horizon == timedelta(minutes=15))
        .filter(
            (Power.datetime >= as_bvp_time(datetime(2015, 1, 1, 20)))
            & (Power.datetime < as_bvp_time(datetime(2015, 1, 1, 22)))
        )
        .all()
    )
    if 3 in job_ids:
        assert len(forecasts) == 8
        overall_expected += 8
    else:
        assert len(forecasts) == 0

    # this is all the forecasts that were made and they all are numbers
    all_forecasts = Power.query.filter(Power.horizon == timedelta(minutes=15)).all()
    assert len(all_forecasts) == overall_expected
    assert all([not np.isnan(f.value) for f in all_forecasts])

    return True
