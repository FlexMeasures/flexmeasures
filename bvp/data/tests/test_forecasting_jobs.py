# flake8: noqa: E402
from datetime import datetime, timedelta
import os

import numpy as np

if os.name == "nt":
    from rq_win import WindowsWorker as SimpleWorker
else:
    from rq import SimpleWorker
from rq.job import Job

from bvp.data.models.data_sources import DataSource
from bvp.data.models.assets import Asset, Power
from bvp.data.services.forecasting import data_source_label, create_forecasting_jobs
from bvp.utils.time_utils import as_bvp_time


def custom_model_params():
    """ little training as we have little data, turn off transformations until they let this test run (TODO) """
    return dict(
        training_and_testing_period=timedelta(hours=2),
        outcome_var_transformation=None,
        regressor_transformation={},
    )


def get_data_source():
    return DataSource.query.filter(DataSource.label == data_source_label).one_or_none()


def work_on_rq(app, exc_handler=None):
    exc_handlers = []
    if exc_handler is not None:
        exc_handlers.append(exc_handler)
    worker = SimpleWorker(
        [app.redis_queue],
        connection=app.redis_queue.connection,
        exception_handlers=exc_handlers,
    )
    worker.work(burst=True)


def check_aggregate(overall_expected: int, horizon: timedelta):
    """Check that the expected number of forecasts were made for the given horizon,
    and check that each forecast is a number."""
    all_forecasts = Power.query.filter(Power.horizon == horizon).all()
    assert len(all_forecasts) == overall_expected
    assert all([not np.isnan(f.value) for f in all_forecasts])


def test_forecasting_an_hour_of_wind(db, app):
    """Test one clean run of one job:
    - data source was made,
    - forecasts have been made
    """
    wind_device_1 = Asset.query.filter_by(name="wind-asset-1").one_or_none()

    assert get_data_source() is None

    # makes 4 forecasts
    horizon = timedelta(hours=1)
    job = create_forecasting_jobs(
        timed_value_type="Power",
        start_of_roll=as_bvp_time(datetime(2015, 1, 1, 6)),
        end_of_roll=as_bvp_time(datetime(2015, 1, 1, 7)),
        horizons=[horizon],
        asset_id=wind_device_1.id,
        custom_model_params=custom_model_params(),
    )

    print("Job: %s" % job[0].id)

    work_on_rq(app, exc_handler=worker_exception_handler)

    assert get_data_source() is not None

    forecasts = (
        Power.query.filter(Power.asset_id == wind_device_1.id)
        .filter(Power.horizon == horizon)
        .filter(
            (Power.datetime >= as_bvp_time(datetime(2015, 1, 1, 7)))
            & (Power.datetime < as_bvp_time(datetime(2015, 1, 1, 8)))
        )
        .all()
    )
    assert len(forecasts) == 4
    check_aggregate(4, horizon)


def test_forecasting_three_hours_of_wind(db, app):
    wind_device2: Asset = Asset.query.filter_by(name="wind-asset-2").one_or_none()

    # makes 12 forecasts
    horizon = timedelta(hours=1)
    job = create_forecasting_jobs(
        timed_value_type="Power",
        start_of_roll=as_bvp_time(datetime(2015, 1, 1, 10)),
        end_of_roll=as_bvp_time(datetime(2015, 1, 1, 13)),
        horizons=[horizon],
        asset_id=wind_device2.id,
        custom_model_params=custom_model_params(),
    )
    print("Job: %s" % job[0].id)

    work_on_rq(app, exc_handler=worker_exception_handler)

    forecasts = (
        Power.query.filter(Power.asset_id == wind_device2.id)
        .filter(Power.horizon == horizon)
        .filter(
            (Power.datetime >= as_bvp_time(datetime(2015, 1, 1, 11)))
            & (Power.datetime < as_bvp_time(datetime(2015, 1, 1, 14)))
        )
        .all()
    )
    assert len(forecasts) == 12
    check_aggregate(12, horizon)


def test_forecasting_two_hours_of_solar(db, app):
    solar_device1: Asset = Asset.query.filter_by(name="solar-asset-1").one_or_none()

    # makes 8 forecasts
    horizon = timedelta(hours=1)
    job = create_forecasting_jobs(
        timed_value_type="Power",
        start_of_roll=as_bvp_time(datetime(2015, 1, 1, 12)),
        end_of_roll=as_bvp_time(datetime(2015, 1, 1, 14)),
        horizons=[horizon],
        asset_id=solar_device1.id,
        custom_model_params=custom_model_params(),
    )
    print("Job: %s" % job[0].id)

    work_on_rq(app, exc_handler=worker_exception_handler)
    forecasts = (
        Power.query.filter(Power.asset_id == solar_device1.id)
        .filter(Power.horizon == horizon)
        .filter(
            (Power.datetime >= as_bvp_time(datetime(2015, 1, 1, 13)))
            & (Power.datetime < as_bvp_time(datetime(2015, 1, 1, 15)))
        )
        .all()
    )
    assert len(forecasts) == 8
    check_aggregate(8, horizon)


def test_forecasting_two_hours_of_solar_at_edge_of_data_set(db, app):
    solar_device1: Asset = Asset.query.filter_by(name="solar-asset-1").one_or_none()

    last_power_datetime = (
        (
            Power.query.filter(Power.asset_id == solar_device1.id)
            .filter(Power.horizon == timedelta(hours=0))
            .order_by(Power.datetime.desc())
        )
        .first()
        .datetime
    )  # datetime index of the last power value 11.45pm (Jan 1st)

    # makes 4 forecasts, 1 of which is for a new datetime index
    horizon = timedelta(hours=6)
    job = create_forecasting_jobs(
        timed_value_type="Power",
        start_of_roll=last_power_datetime
        - horizon
        - timedelta(minutes=30),  # start of data on which forecast is based (5.15pm)
        end_of_roll=last_power_datetime
        - horizon
        + timedelta(minutes=30),  # end of data on which forecast is based (6.15pm)
        horizons=[
            timedelta(hours=6)
        ],  # so we want forecasts for 11.15pm (Jan 1st) to 0.15am (Jan 2nd)
        asset_id=solar_device1.id,
        custom_model_params=custom_model_params(),
    )
    print("Job: %s" % job[0].id)

    work_on_rq(app, exc_handler=worker_exception_handler)

    forecasts = (
        Power.query.filter(Power.asset_id == solar_device1.id)
        .filter(Power.horizon == horizon)
        .filter(Power.datetime > last_power_datetime)
        .all()
    )
    assert len(forecasts) == 1
    check_aggregate(4, horizon)


def worker_exception_handler(job, exc_type, exc_value, traceback):
    print("WORKER EXCEPTION HANDLED: %s:%s" % (exc_type, exc_value))


def check_failure(redis_queue, search_word: str):
    """Check that there was one failure, with a search word mentioned"""
    if os.name == "nt":
        print("Failed job registry not working on Windows. Skipping check...")
        return
    failed = redis_queue.failed_job_registry
    assert failed.count == 1
    job = Job.fetch(failed.get_job_ids()[0], connection=redis_queue.connection)
    assert search_word in job.exc_info


def test_failed_forecasting_insufficient_data(app):
    # This one should fail as there is no underlying data - and due to the start date it is the last to be picked.
    solar_device1: Asset = Asset.query.filter_by(name="solar-asset-1").one_or_none()
    create_forecasting_jobs(
        timed_value_type="Power",
        start_of_roll=as_bvp_time(datetime(2016, 1, 1, 20)),
        end_of_roll=as_bvp_time(datetime(2016, 1, 1, 22)),
        horizons=[timedelta(hours=1)],
        asset_id=solar_device1.id,
        custom_model_params=custom_model_params(),
    )
    work_on_rq(app, exc_handler=worker_exception_handler)
    check_failure(app.redis_queue, "NotEnoughDataException")


def test_failed_forecasting_invalid_horizon(app):
    # This one should fail as the horizon is invalid
    solar_device1: Asset = Asset.query.filter_by(name="solar-asset-1").one_or_none()
    create_forecasting_jobs(
        timed_value_type="Power",
        start_of_roll=as_bvp_time(datetime(2015, 1, 1, 21)),
        end_of_roll=as_bvp_time(datetime(2015, 1, 1, 23)),
        horizons=[timedelta(hours=18)],
        asset_id=solar_device1.id,
        custom_model_params=custom_model_params(),
    )
    work_on_rq(app, exc_handler=worker_exception_handler)
    check_failure(app.redis_queue, "InvalidHorizonException")
