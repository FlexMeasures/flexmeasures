from typing import Union, List, Optional
from datetime import datetime, timedelta

from ts_forecasting_pipeline.forecasting import make_rolling_forecasts

from bvp.utils.time_utils import bvp_now, as_bvp_time, forecast_horizons_for
from bvp.data.models.forecasting.jobs import ForecastingJob
from bvp.data.models.forecasting.generic import (
    latest_model as latest_generic_model,
    latest_version as latest_generic_model_version,
    latest_params_by_asset_type as latest_generic_params_by_asset_type,
)
from bvp.data.models.data_sources import DataSource
from bvp.data.config import db
from bvp.data.transactional import PartialTaskCompletionException
from bvp.data.models.weather import Weather
from bvp.data.models.assets import Power
from bvp.data.models.markets import Price
from bvp.data.models.utils import determine_asset_type_by_asset
from bvp.data.transactional import task_with_status_report
from bvp.data.models.forecasting import NotEnoughDataException


data_source_label = "forecast by Seita (%s)" % latest_generic_model_version()


@task_with_status_report
def run_forecasting_jobs(
    max_forecasts: int,
    horizon: Optional[timedelta] = None,
    custom_model_params: dict = None,
):
    """
    Find forecasting jobs in the database and work on them.
    Only select as many jobs as limited by the number of forecasts.
    """
    jobs_to_run = get_jobs_to_run(max_forecasts, horizon)

    if not jobs_to_run:
        print("There seem to be no forecasting jobs I could run. Exiting ...")
        return

    # Mark these jobs with in_progress_since=now and flush already, so that no other runner will take them
    # while we work on them. If an exception occurs, they will be free again
    for job in jobs_to_run:
        job.in_progress_since = bvp_now()
    db.session.flush()

    run_and_report_on_jobs(jobs_to_run, custom_model_params)


def reactivate_dead_jobs():
    """Check if old (older than one hour) jobs need to be re-activated (in_process_since = null)"""
    dead_jobs = ForecastingJob.query.filter(
        ForecastingJob.in_progress_since <= bvp_now() - timedelta(hours=1)
    ).all()
    if dead_jobs:
        for job in dead_jobs:
            print("Trying to wake %s from the dead ..." % job)
            job.in_progress_since = None
            db.session.add(job)


def get_jobs_to_run(
    max_forecasts: int, horizon: Optional[timedelta] = None
) -> List[ForecastingJob]:
    reactivate_dead_jobs()
    q = ForecastingJob.query.filter(ForecastingJob.in_progress_since.is_(None))
    if horizon is not None:
        q = q.filter(ForecastingJob.horizon == horizon)
    jobs = q.order_by(ForecastingJob.start.desc(), ForecastingJob.id.desc()).all()

    # Calculate which jobs (sorted by id asc) can be done (number of forecasts fits into
    # max_forecasts_per_run parameter)
    jobs_to_run = []
    planned_forecasts = 0
    while jobs:
        next_job = jobs.pop()
        model_params = latest_generic_params_by_asset_type(
            determine_asset_type_by_asset(next_job.get_asset())
        )
        next_job_num_forecasts = next_job.num_forecasts(model_params["resolution"])
        if planned_forecasts + next_job_num_forecasts <= max_forecasts:
            jobs_to_run.append(next_job)
            planned_forecasts += next_job_num_forecasts
        else:
            break
    return jobs_to_run


def get_data_source() -> DataSource:
    """Make sure we have a data source"""
    data_source = DataSource.query.filter(
        DataSource.label == data_source_label
    ).one_or_none()
    if data_source is None:
        data_source = DataSource(label=data_source_label, type="script")
        db.session.add(data_source)
    return data_source


def run_job(
    job: ForecastingJob, data_source: DataSource, custom_model_params: dict = None
):
    """
    Build model for this job, make rolling forecasts, save the forecasts made, finally delete the job.
    """
    print("Running ForecastingJob %d: %s" % (job.id, job))

    if len(forecast_horizons_for(job.horizon)) == 0:
        raise Exception("Invalid horizon on job %d: %s" % (job.id, job.horizon))

    model_specs, model_identifier = latest_generic_model(
        generic_asset=job.get_asset(),
        start=as_bvp_time(job.start),
        end=as_bvp_time(job.end),
        horizon=job.horizon,
        custom_model_params=custom_model_params,
    )
    model_specs.creation_time = bvp_now()

    forecasts, model_state = make_rolling_forecasts(
        start=as_bvp_time(job.start), end=as_bvp_time(job.end), model_specs=model_specs
    )

    ts_value_forecasts = [
        make_timed_value(
            job.timed_value_type, job.asset_id, dt, value, job.horizon, data_source.id
        )
        for dt, value in forecasts.items()
    ]

    db.session.bulk_save_objects(ts_value_forecasts)

    ForecastingJob.query.filter_by(id=job.id).delete()


def run_and_report_on_jobs(jobs: List[ForecastingJob], custom_model_params):
    """Run the jobs, and report failures in a practical way"""
    data_source = get_data_source()
    expected_successes = len(jobs)
    seen_successes = 0
    jobs_removed = 0

    for job in jobs:
        db.session.begin_nested()  # roll back to here if the job failed
        try:
            run_job(job, data_source, custom_model_params)
            print("Successfully ran job %d." % job.id)
            seen_successes += 1
        except Exception as e:
            print("Could not run job %d: %s" % (job.id, str(e)))
            db.session.rollback()
            if e.__class__ == NotEnoughDataException:
                print("Not enough data for job %d - will be deleted." % job.id)
                ForecastingJob.query.filter_by(id=job.id).delete()
                expected_successes -= 1
                jobs_removed += 1
            else:
                job.in_progress_since = None

    if seen_successes < expected_successes:
        if seen_successes == 0:
            # This avoids a commit
            raise Exception(
                "Of %d jobs, none succeeded. %d jobs removed due to missing data."
                % (expected_successes, jobs_removed)
            )
        else:
            # by raising this Exception type, the data which we generated will get committed.
            raise PartialTaskCompletionException(
                "Of %d jobs, only %d succeeded. %d jobs removed due to missing data."
                % (expected_successes, seen_successes, jobs_removed)
            )


# --- the function below can hopefully go away if we refactor a real generic asset class


def make_timed_value(
    timed_value_type: str,
    asset_id: int,
    dt: datetime,
    value: float,
    horizon: timedelta,
    data_source_id: int,
) -> Union[Power, Price, Weather]:
    if timed_value_type not in ("Power", "Price", "Weather"):
        raise ("Cannot get asset for asset_type '%s'" % timed_value_type)
    ts_value = None
    if timed_value_type == "Power":
        ts_value = Power(
            datetime=dt,
            horizon=horizon,
            value=value,
            asset_id=asset_id,
            data_source_id=data_source_id,
        )
    elif timed_value_type == "Price":
        ts_value = Price(
            datetime=dt,
            horizon=horizon,
            value=value,
            market_id=asset_id,
            data_source_id=data_source_id,
        )
    elif timed_value_type == "Weather":
        ts_value = Weather(
            datetime=dt,
            horizon=horizon,
            value=value,
            sensor_id=asset_id,
            data_source_id=data_source_id,
        )
    if ts_value is None:
        raise (
            "Cannot create asset of type %s with id %d" % (timed_value_type, asset_id)
        )
    return ts_value
