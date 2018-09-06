from datetime import datetime, timedelta

import pytz
import pytest
import numpy as np

from bvp.data.models.forecasting.jobs import ForecastingJob
from bvp.data.models.data_sources import DataSource
from bvp.data.models.assets import AssetType, Asset, Power
from bvp.data.models.task_runs import LatestTaskRun
from bvp.data.scripts.make_forecasts import run_forecasting_jobs, data_source_label
from bvp.utils.time_utils import bvp_now


@pytest.fixture(scope="function", autouse=True)
def remove_seasonality_for_power_forecasts(db):
    """Make sure the AssetType specs make us query only data we actually have in the test db"""
    asset_types = AssetType.query.all()
    for a in asset_types:
        a.daily_seasonality = False
        a.weekly_seasonality = False
        a.yearly_seasoanlity = False


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

    forecasts = Power.make_query(
        asset_name="wind-asset-1",
        query_window=(datetime(2015, 1, 1, 6), datetime(2015, 1, 1, 7)),
        horizon_window=(timedelta(minutes=15), timedelta(minutes=15)),
    ).all()
    assert len(forecasts) == 4
    assert all([not np.isnan(f.value) for f in forecasts])


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

    run_forecasting_jobs(
        max_forecasts=25,
        custom_model_params=dict(
            training_and_testing_period=timedelta(hours=2),
            outcome_var_transformation=None,
            regressor_transformation={},
        ),
    )

    left_jobs = ForecastingJob.query.all()
    # fetch running job again from the new session (which run_forecasting_jobs opened)
    # wind2: Asset = Asset.query.filter_by(name="wind-asset-2").one_or_none()
    # running_job: ForecastingJob = ForecastingJob.query.filter_by(
    #     asset_id=wind2.id
    # ).one_or_none()
    assert len(left_jobs) == 2
    assert left_jobs[0].id == running_job.id

    forecasts = Power.make_query(
        asset_name="wind-asset-1",
        query_window=(datetime(2015, 1, 1, 6), datetime(2015, 1, 1, 7)),
        horizon_window=(timedelta(minutes=15), timedelta(minutes=15)),
    ).all()
    assert len(forecasts) == 4
    assert all([not np.isnan(f.value) for f in forecasts])

    forecasts = Power.make_query(
        asset_name="wind-asset-2",
        query_window=(datetime(2015, 1, 1, 14), datetime(2015, 1, 1, 17)),
        horizon_window=(timedelta(minutes=15), timedelta(minutes=15)),
    ).all()
    assert len(forecasts) == 0

    forecasts = Power.make_query(
        asset_name="solar-asset-1",
        query_window=(datetime(2015, 1, 1, 20), datetime(2015, 1, 1, 22)),
        horizon_window=(timedelta(minutes=15), timedelta(minutes=15)),
    ).all()
    assert len(forecasts) == 8
    assert all([not np.isnan(f.value) for f in forecasts])


def test_failure(db):
    """When we include the last job with an invalid range, nothing should get done in the end.
    This is not testeed here, though, as the session is still running. Needs improvement."""

    # initial_num_jobs = ForecastingJob.query.count()

    run_forecasting_jobs(
        max_forecasts=100,  # including the last, failing one
        custom_model_params=dict(
            training_and_testing_period=timedelta(hours=2),
            outcome_var_transformation=None,
            regressor_transformation={},
        ),
    )

    assert (
        ForecastingJob.query.count() == 1
    )  # TODO: how to test that if the session rolls back, it'd be initial_num_jobs

    assert (
        Power.make_query(
            asset_name="solar-asset-1",
            query_window=(datetime(2014, 12, 1), datetime(2016, 1, 5)),
            horizon_window=(timedelta(minutes=15), timedelta(minutes=15)),
        ).count()
        == 9
    )  # TODO: these are from the third job, which went through, see also comment above, would be 0?

    ltr = LatestTaskRun.query.one_or_none()
    assert ltr.name == "run_forecasting_jobs"
    assert ltr.status is False
    assert ltr.datetime > datetime.utcnow().replace(tzinfo=pytz.utc) - timedelta(
        minutes=2
    )
