from datetime import datetime, timedelta
from typing import List

from flask import current_app
import click
from rq import get_current_job
from rq.job import Job
from timetomodel.forecasting import make_rolling_forecasts
import timely_beliefs as tb

from flexmeasures.data import db
from flexmeasures.data.models.forecasting import lookup_model_specs_configurator
from flexmeasures.data.models.forecasting.exceptions import InvalidHorizonException
from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.data.models.forecasting.utils import (
    get_query_window,
    check_data_availability,
)
from flexmeasures.data.utils import get_data_source, save_to_db
from flexmeasures.utils.time_utils import (
    as_server_time,
    server_now,
    forecast_horizons_for,
    supported_horizons,
)

"""
The life cycle of a forecasting job:
1. A forecasting job is born in create_forecasting_jobs.
2. It is run in make_rolling_viewpoint_forecasts or make_fixed_viewpoint_forecasts, which write results to the db.
   This is also where model specs are configured and a possible fallback model is stored for step 3.
3. If an error occurs (and the worker is configured accordingly), handle_forecasting_exception comes in.
   This might re-enqueue the job or try a different model (which creates a new job).
"""


# TODO: we could also monitor the failed queue and re-enqueue jobs who had missing data
#       (and maybe failed less than three times so far)


class MisconfiguredForecastingJobException(Exception):
    pass


def create_forecasting_jobs(
    sensor_id: int,
    start_of_roll: datetime,
    end_of_roll: datetime,
    resolution: timedelta = None,
    horizons: List[timedelta] = None,
    model_search_term="linear-OLS",
    custom_model_params: dict = None,
    enqueue: bool = True,
) -> List[Job]:
    """Create forecasting jobs by rolling through a time window, for a number of given forecast horizons.
    Start and end of the forecasting jobs are equal to the time window (start_of_roll, end_of_roll) plus the horizon.

    For example (with shorthand notation):

        start_of_roll = 3pm
        end_of_roll = 5pm
        resolution = 15min
        horizons = [1h, 6h, 1d]

        This creates the following 3 jobs:

        1) forecast each quarter-hour from 4pm to 6pm, i.e. the 1h forecast
        2) forecast each quarter-hour from 9pm to 11pm, i.e. the 6h forecast
        3) forecast each quarter-hour from 3pm to 5pm the next day, i.e. the 1d forecast

    If not given, relevant horizons are derived from the resolution of the posted data.

    The job needs a model configurator, for which you can supply a model search term. If omitted, the
    current default model configuration will be used.

    It's possible to customize model parameters, but this feature is (currently) meant to only
    be used by tests, so that model behaviour can be adapted to test conditions. If used outside
    of testing, an exception is raised.

    if enqueue is True (default), the jobs are put on the redis queue.

    Returns the redis-queue forecasting jobs which were created.
    """
    if not current_app.testing and custom_model_params is not None:
        raise MisconfiguredForecastingJobException(
            "Model parameters can only be customized during testing."
        )
    if horizons is None:
        if resolution is None:
            raise MisconfiguredForecastingJobException(
                "Cannot create forecasting jobs - set either horizons or resolution."
            )
        horizons = forecast_horizons_for(resolution)
    jobs: List[Job] = []
    for horizon in horizons:
        job = Job.create(
            make_rolling_viewpoint_forecasts,
            kwargs=dict(
                sensor_id=sensor_id,
                horizon=horizon,
                start=start_of_roll + horizon,
                end=end_of_roll + horizon,
                custom_model_params=custom_model_params,
            ),
            connection=current_app.queues["forecasting"].connection,
            ttl=int(
                current_app.config.get(
                    "FLEXMEASURES_JOB_TTL", timedelta(-1)
                ).total_seconds()
            ),
        )
        job.meta["model_search_term"] = model_search_term
        job.save_meta()
        jobs.append(job)
        if enqueue:
            current_app.queues["forecasting"].enqueue_job(job)
    return jobs


def make_fixed_viewpoint_forecasts(
    sensor_id: int,
    horizon: timedelta,
    start: datetime,
    end: datetime,
    custom_model_params: dict = None,
) -> int:
    """Build forecasting model specs, make fixed-viewpoint forecasts, and save the forecasts made.

    Each individual forecast is a belief about a time interval.
    Fixed-viewpoint forecasts share the same belief time.
    See the timely-beliefs lib for relevant terminology.
    """
    # todo: implement fixed-viewpoint forecasts
    raise NotImplementedError


def make_rolling_viewpoint_forecasts(
    sensor_id: int,
    horizon: timedelta,
    start: datetime,
    end: datetime,
    custom_model_params: dict = None,
) -> int:
    """Build forecasting model specs, make rolling-viewpoint forecasts, and save the forecasts made.

    Each individual forecast is a belief about a time interval.
    Rolling-viewpoint forecasts share the same belief horizon (the duration between belief time and knowledge time).
    Model specs are also retrained in a rolling fashion, but with its own frequency set in custom_model_params.
    See the timely-beliefs lib for relevant terminology.

    Parameters
    ----------
    :param sensor_id: int
        To identify which sensor to forecast
    :param horizon: timedelta
        duration between the end of each interval and the time at which the belief about that interval is formed
    :param start: datetime
        start of forecast period, i.e. start time of the first interval to be forecast
    :param end: datetime
        end of forecast period, i.e end time of the last interval to be forecast
    :param custom_model_params: dict
        pass in params which will be passed to the model specs configurator,
        e.g. outcome_var_transformation, only advisable to be used for testing.
    :returns: int
        the number of forecasts made
    """
    # https://docs.sqlalchemy.org/en/13/faq/connections.html#how-do-i-use-engines-connections-sessions-with-python-multiprocessing-or-os-fork
    db.engine.dispose()

    rq_job = get_current_job()

    # find out which model to run, fall back to latest recommended
    model_search_term = rq_job.meta.get("model_search_term", "linear-OLS")

    # find sensor
    sensor = Sensor.query.filter_by(id=sensor_id).one_or_none()

    click.echo(
        "Running Forecasting Job %s: %s for %s on model '%s', from %s to %s"
        % (rq_job.id, sensor, horizon, model_search_term, start, end)
    )

    if hasattr(sensor, "market_type"):
        ex_post_horizon = None  # Todo: until we sorted out the ex_post_horizon, use all available price data
    else:
        ex_post_horizon = timedelta(hours=0)

    # Make model specs
    model_configurator = lookup_model_specs_configurator(model_search_term)
    model_specs, model_identifier, fallback_model_search_term = model_configurator(
        sensor=sensor,
        forecast_start=as_server_time(start),
        forecast_end=as_server_time(end),
        forecast_horizon=horizon,
        ex_post_horizon=ex_post_horizon,
        custom_model_params=custom_model_params,
    )
    model_specs.creation_time = server_now()

    rq_job.meta["model_identifier"] = model_identifier
    rq_job.meta["fallback_model_search_term"] = fallback_model_search_term
    rq_job.save()

    # before we run the model, check if horizon is okay and enough data is available
    if horizon not in supported_horizons():
        raise InvalidHorizonException(
            "Invalid horizon on job %s: %s" % (rq_job.id, horizon)
        )

    query_window = get_query_window(
        model_specs.start_of_training,
        end,
        [lag * model_specs.frequency for lag in model_specs.lags],
    )
    check_data_availability(
        sensor,
        TimedBelief,
        start,
        end,
        query_window,
        horizon,
    )

    data_source = get_data_source(
        data_source_name="Seita (%s)"
        % rq_job.meta.get("model_identifier", "unknown model"),
        data_source_type="forecasting script",
    )

    forecasts, model_state = make_rolling_forecasts(
        start=as_server_time(start),
        end=as_server_time(end),
        model_specs=model_specs,
    )
    click.echo("Job %s made %d forecasts." % (rq_job.id, len(forecasts)))

    ts_value_forecasts = [
        TimedBelief(
            event_start=dt,
            belief_horizon=horizon,
            event_value=value,
            sensor=sensor,
            source=data_source,
        )
        for dt, value in forecasts.items()
    ]
    bdf = tb.BeliefsDataFrame(ts_value_forecasts)
    save_to_db(bdf)
    db.session.commit()

    return len(forecasts)


def handle_forecasting_exception(job, exc_type, exc_value, traceback):
    """
    Decide if we can do something about this failure:
    * Try a different model
    * Re-queue at a later time (using rq_scheduler)
    """
    click.echo("HANDLING RQ WORKER EXCEPTION: %s:%s\n" % (exc_type, exc_value))

    if "failures" not in job.meta:
        job.meta["failures"] = 1
    else:
        job.meta["failures"] = job.meta["failures"] + 1
    job.save_meta()

    # We might use this to decide if we want to re-queue a failed job
    # if job.meta['failures'] < 3:
    #     job.queue.failures.requeue(job)

    # TODO: use this to add more meta information?
    # if exc_type == NotEnoughDataException:

    if "fallback_model_search_term" in job.meta:
        if job.meta["fallback_model_search_term"] is not None:
            new_job = Job.create(
                make_rolling_viewpoint_forecasts,
                args=job.args,
                kwargs=job.kwargs,
                connection=current_app.queues["forecasting"].connection,
            )
            new_job.meta["model_search_term"] = job.meta["fallback_model_search_term"]
            new_job.save_meta()
            current_app.queues["forecasting"].enqueue_job(new_job)


def num_forecasts(start: datetime, end: datetime, resolution: timedelta) -> int:
    """Compute how many forecasts a job needs to make, given a resolution"""
    return (end - start) // resolution
