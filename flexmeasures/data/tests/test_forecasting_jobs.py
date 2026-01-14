# flake8: noqa: E402
from __future__ import annotations

from datetime import datetime, timedelta
import os

import numpy as np
from rq.job import Job

from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.data.tests.utils import work_on_rq
from flexmeasures.data.services.forecasting import (
    create_forecasting_jobs,
    handle_forecasting_exception,
)
from flexmeasures.utils.time_utils import as_server_time


def custom_model_params():
    """little training as we have little data, turn off transformations until they let this test run (TODO)"""
    return dict(
        training_and_testing_period=timedelta(hours=2),
        outcome_var_transformation=None,
        regressor_transformation={},
    )


def get_data_source(model_identifier: str = "linear-OLS model v2"):
    """This helper is a good way to check which model has been successfully used.
    Only when the forecasting job is successful, will the created data source entry not be rolled back.
    """
    data_source_name = "Seita (%s)" % model_identifier
    return DataSource.query.filter_by(
        name=data_source_name, type="forecasting script"
    ).one_or_none()


def check_aggregate(overall_expected: int, horizon: timedelta, sensor_id: int):
    """Check that the expected number of forecasts were made for the given horizon,
    and check that each forecast is a number."""
    all_forecasts = (
        TimedBelief.query.filter(TimedBelief.sensor_id == sensor_id)
        .filter(TimedBelief.belief_horizon == horizon)
        .all()
    )
    assert len(all_forecasts) == overall_expected
    assert all([not np.isnan(f.event_value) for f in all_forecasts])


def test_forecasting_an_hour_of_wind(db, run_as_cli, app, setup_test_data):
    """Test one clean run of one job:
    - data source was made,
    - forecasts have been made
    """
    # asset has only 1 power sensor
    wind_device_1: Sensor = setup_test_data["wind-asset-1"].sensors[0]

    # Remove each seasonality, so we don't query test data that isn't there
    wind_device_1.set_attribute("daily_seasonality", False)
    wind_device_1.set_attribute("weekly_seasonality", False)
    wind_device_1.set_attribute("yearly_seasonality", False)

    assert get_data_source() is None

    # makes 4 forecasts
    horizon = timedelta(hours=1)
    job = create_forecasting_jobs(
        start_of_roll=as_server_time(datetime(2015, 1, 1, 6)),
        end_of_roll=as_server_time(datetime(2015, 1, 1, 7)),
        horizons=[horizon],
        sensor_id=wind_device_1.id,
        custom_model_params=custom_model_params(),
    )

    print("Job: %s" % job[0].id)

    work_on_rq(app.queues["forecasting"], exc_handler=handle_forecasting_exception)

    assert get_data_source() is not None

    forecasts = (
        TimedBelief.query.filter(TimedBelief.sensor_id == wind_device_1.id)
        .filter(TimedBelief.belief_horizon == horizon)
        .filter(
            (TimedBelief.event_start >= as_server_time(datetime(2015, 1, 1, 7)))
            & (TimedBelief.event_start < as_server_time(datetime(2015, 1, 1, 8)))
        )
        .all()
    )
    assert len(forecasts) == 4
    check_aggregate(4, horizon, wind_device_1.id)


def test_forecasting_two_hours_of_solar_at_edge_of_data_set(
    db, run_as_cli, app, setup_test_data
):
    # asset has only 1 power sensor
    solar_device_1: Sensor = setup_test_data["solar-asset-1"].sensors[0]

    last_power_datetime = (
        (
            TimedBelief.query.filter(TimedBelief.sensor_id == solar_device_1.id)
            .filter(TimedBelief.belief_horizon == timedelta(hours=0))
            .order_by(TimedBelief.event_start.desc())
        )
        .first()
        .event_start
    )  # datetime index of the last power value 11.45pm (Jan 1st)

    # makes 4 forecasts, 1 of which is for a new datetime index
    horizon = timedelta(hours=6)
    job = create_forecasting_jobs(
        start_of_roll=last_power_datetime
        - horizon
        - timedelta(minutes=30),  # start of data on which forecast is based (5.15pm)
        end_of_roll=last_power_datetime
        - horizon
        + timedelta(minutes=30),  # end of data on which forecast is based (6.15pm)
        horizons=[
            timedelta(hours=6)
        ],  # so we want forecasts for 11.15pm (Jan 1st) to 0.15am (Jan 2nd)
        sensor_id=solar_device_1.id,
        custom_model_params=custom_model_params(),
    )
    print("Job: %s" % job[0].id)

    work_on_rq(app.queues["forecasting"], exc_handler=handle_forecasting_exception)

    forecasts = (
        TimedBelief.query.filter(TimedBelief.sensor_id == solar_device_1.id)
        .filter(TimedBelief.belief_horizon == horizon)
        .filter(TimedBelief.event_start > last_power_datetime)
        .all()
    )
    assert len(forecasts) == 1
    check_aggregate(4, horizon, solar_device_1.id)


def check_failures(
    redis_queue,
    failure_search_words: list[str] | None = None,
    model_identifiers: list[str] | None = None,
):
    """Check that there was at least one failure.
    For each failure, the exception message can be checked for a search word
    and the model identifier can also be compared to a string.
    """
    if os.name == "nt":
        print("Failed job registry not working on Windows. Skipping check...")
        return
    failed = redis_queue.failed_job_registry

    if failure_search_words is None:
        failure_search_words = []
    if model_identifiers is None:
        model_identifiers = []

    failure_count = max(len(failure_search_words), len(model_identifiers), 1)

    print(
        "FAILURE QUEUE: %s"
        % [
            Job.fetch(jid, connection=redis_queue.connection).meta
            for jid in failed.get_job_ids()
        ]
    )
    assert failed.count == failure_count

    for job_idx in range(failure_count):
        job = Job.fetch(
            failed.get_job_ids()[job_idx], connection=redis_queue.connection
        )

        if len(failure_search_words) >= job_idx:
            assert failure_search_words[job_idx] in job.latest_result().exc_string

        if model_identifiers:
            assert job.meta["model_identifier"] == model_identifiers[job_idx]


def test_failed_forecasting_insufficient_data(
    app, run_as_cli, clean_redis, setup_test_data
):
    """This one (as well as the fallback) should fail as there is no underlying data.
    (Power data is in 2015)"""

    # asset has only 1 power sensor
    solar_device_1: Sensor = setup_test_data["solar-asset-1"].sensors[0]

    create_forecasting_jobs(
        start_of_roll=as_server_time(datetime(2016, 1, 1, 20)),
        end_of_roll=as_server_time(datetime(2016, 1, 1, 22)),
        horizons=[timedelta(hours=1)],
        sensor_id=solar_device_1.id,
        custom_model_params=custom_model_params(),
    )
    work_on_rq(app.queues["forecasting"], exc_handler=handle_forecasting_exception)
    check_failures(app.queues["forecasting"], 2 * ["NotEnoughDataException"])


def test_failed_forecasting_invalid_horizon(
    app, run_as_cli, clean_redis, setup_test_data
):
    """This one (as well as the fallback) should fail as the horizon is invalid."""

    # asset has only 1 power sensor
    solar_device_1: Sensor = setup_test_data["solar-asset-1"].sensors[0]

    create_forecasting_jobs(
        start_of_roll=as_server_time(datetime(2015, 1, 1, 21)),
        end_of_roll=as_server_time(datetime(2015, 1, 1, 23)),
        horizons=[timedelta(hours=18)],
        sensor_id=solar_device_1.id,
        custom_model_params=custom_model_params(),
    )
    work_on_rq(app.queues["forecasting"], exc_handler=handle_forecasting_exception)
    check_failures(app.queues["forecasting"], 2 * ["InvalidHorizonException"])


def test_failed_unknown_model(app, clean_redis, setup_test_data):
    """This one should fail because we use a model search term which yields no model configurator."""

    # asset has only 1 power sensor
    solar_device_1: Sensor = setup_test_data["solar-asset-1"].sensors[0]

    horizon = timedelta(hours=1)

    cmp = custom_model_params()
    cmp["training_and_testing_period"] = timedelta(days=365)

    create_forecasting_jobs(
        start_of_roll=as_server_time(datetime(2015, 1, 1, 12)),
        end_of_roll=as_server_time(datetime(2015, 1, 1, 14)),
        horizons=[horizon],
        sensor_id=solar_device_1.id,
        model_search_term="no-one-knows-this",
        custom_model_params=cmp,
    )
    work_on_rq(app.queues["forecasting"], exc_handler=handle_forecasting_exception)

    check_failures(app.queues["forecasting"], ["No model found for search term"])
