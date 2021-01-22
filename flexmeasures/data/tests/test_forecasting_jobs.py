# flake8: noqa: E402
from typing import Optional, List
from datetime import datetime, timedelta
import os

import pytest
import numpy as np
from sqlalchemy.orm import Query
from rq.job import Job

from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.assets import Asset, Power
from flexmeasures.data.tests.utils import work_on_rq
from flexmeasures.data.services.forecasting import (
    create_forecasting_jobs,
    handle_forecasting_exception,
)
from flexmeasures.utils.time_utils import as_server_time


def custom_model_params():
    """ little training as we have little data, turn off transformations until they let this test run (TODO) """
    return dict(
        training_and_testing_period=timedelta(hours=2),
        outcome_var_transformation=None,
        regressor_transformation={},
    )


def get_data_source(model_identifier: str = "linear-OLS model v2"):
    """This helper is a good way to check which model has been successfully used.
    Only when the forecasting job is successful, will the created data source entry not be rolled back."""
    data_source_name = "Seita (%s)" % model_identifier
    return DataSource.query.filter_by(
        name=data_source_name, type="forecasting script"
    ).one_or_none()


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
        start_of_roll=as_server_time(datetime(2015, 1, 1, 6)),
        end_of_roll=as_server_time(datetime(2015, 1, 1, 7)),
        horizons=[horizon],
        asset_id=wind_device_1.id,
        custom_model_params=custom_model_params(),
    )

    print("Job: %s" % job[0].id)

    work_on_rq(app.queues["forecasting"], exc_handler=handle_forecasting_exception)

    assert get_data_source() is not None

    forecasts = (
        Power.query.filter(Power.asset_id == wind_device_1.id)
        .filter(Power.horizon == horizon)
        .filter(
            (Power.datetime >= as_server_time(datetime(2015, 1, 1, 7)))
            & (Power.datetime < as_server_time(datetime(2015, 1, 1, 8)))
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
        start_of_roll=as_server_time(datetime(2015, 1, 1, 10)),
        end_of_roll=as_server_time(datetime(2015, 1, 1, 13)),
        horizons=[horizon],
        asset_id=wind_device2.id,
        custom_model_params=custom_model_params(),
    )
    print("Job: %s" % job[0].id)

    work_on_rq(app.queues["forecasting"], exc_handler=handle_forecasting_exception)

    forecasts = (
        Power.query.filter(Power.asset_id == wind_device2.id)
        .filter(Power.horizon == horizon)
        .filter(
            (Power.datetime >= as_server_time(datetime(2015, 1, 1, 11)))
            & (Power.datetime < as_server_time(datetime(2015, 1, 1, 14)))
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
        start_of_roll=as_server_time(datetime(2015, 1, 1, 12)),
        end_of_roll=as_server_time(datetime(2015, 1, 1, 14)),
        horizons=[horizon],
        asset_id=solar_device1.id,
        custom_model_params=custom_model_params(),
    )
    print("Job: %s" % job[0].id)

    work_on_rq(app.queues["forecasting"], exc_handler=handle_forecasting_exception)
    forecasts = (
        Power.query.filter(Power.asset_id == solar_device1.id)
        .filter(Power.horizon == horizon)
        .filter(
            (Power.datetime >= as_server_time(datetime(2015, 1, 1, 13)))
            & (Power.datetime < as_server_time(datetime(2015, 1, 1, 15)))
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

    work_on_rq(app.queues["forecasting"], exc_handler=handle_forecasting_exception)

    forecasts = (
        Power.query.filter(Power.asset_id == solar_device1.id)
        .filter(Power.horizon == horizon)
        .filter(Power.datetime > last_power_datetime)
        .all()
    )
    assert len(forecasts) == 1
    check_aggregate(4, horizon)


def check_failures(
    redis_queue,
    failure_search_words: Optional[List[str]] = None,
    model_identifiers: Optional[List[str]] = None,
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
            assert failure_search_words[job_idx] in job.exc_info

        if model_identifiers:
            assert job.meta["model_identifier"] == model_identifiers[job_idx]


def test_failed_forecasting_insufficient_data(app):
    """This one (as well as the fallback) should fail as there is no underlying data.
    (Power data is in 2015)"""
    solar_device1: Asset = Asset.query.filter_by(name="solar-asset-1").one_or_none()
    create_forecasting_jobs(
        timed_value_type="Power",
        start_of_roll=as_server_time(datetime(2016, 1, 1, 20)),
        end_of_roll=as_server_time(datetime(2016, 1, 1, 22)),
        horizons=[timedelta(hours=1)],
        asset_id=solar_device1.id,
        custom_model_params=custom_model_params(),
    )
    work_on_rq(app.queues["forecasting"], exc_handler=handle_forecasting_exception)
    check_failures(app.queues["forecasting"], 2 * ["NotEnoughDataException"])


def test_failed_forecasting_invalid_horizon(app):
    """ This one (as well as the fallback) should fail as the horizon is invalid."""
    solar_device1: Asset = Asset.query.filter_by(name="solar-asset-1").one_or_none()
    create_forecasting_jobs(
        timed_value_type="Power",
        start_of_roll=as_server_time(datetime(2015, 1, 1, 21)),
        end_of_roll=as_server_time(datetime(2015, 1, 1, 23)),
        horizons=[timedelta(hours=18)],
        asset_id=solar_device1.id,
        custom_model_params=custom_model_params(),
    )
    work_on_rq(app.queues["forecasting"], exc_handler=handle_forecasting_exception)
    check_failures(app.queues["forecasting"], 2 * ["InvalidHorizonException"])


def test_failed_unknown_model(app):
    """ This one should fail because we use a model search term which yields no model configurator."""
    solar_device1: Asset = Asset.query.filter_by(name="solar-asset-1").one_or_none()
    horizon = timedelta(hours=1)

    cmp = custom_model_params()
    cmp["training_and_testing_period"] = timedelta(days=365)

    create_forecasting_jobs(
        timed_value_type="Power",
        start_of_roll=as_server_time(datetime(2015, 1, 1, 12)),
        end_of_roll=as_server_time(datetime(2015, 1, 1, 14)),
        horizons=[horizon],
        asset_id=solar_device1.id,
        model_search_term="no-one-knows-this",
        custom_model_params=cmp,
    )
    work_on_rq(app.queues["forecasting"], exc_handler=handle_forecasting_exception)

    check_failures(app.queues["forecasting"], ["No model found for search term"])


@pytest.mark.parametrize(
    "model_to_start_with, model_version", [("failing-test", 1), ("linear-OLS", 2)]
)
def test_failed_model_with_too_much_training_then_succeed_with_fallback(
    app, model_to_start_with, model_version
):
    """
    Here we fail once - because we start with a model that needs too much training.
    So we check for this failure happening as expected.
    But then, we do succeed with the fallback model one level down.
    (fail-test falls back to linear & linear falls back to naive).
    As a result, there should be forecasts in the DB.
    """
    solar_device1: Asset = Asset.query.filter_by(name="solar-asset-1").one_or_none()
    horizon_hours = 1
    horizon = timedelta(hours=horizon_hours)

    cmp = custom_model_params()
    hour_start = 5
    if model_to_start_with == "linear-OLS":
        # making the linear model fail and fall back to naive
        hour_start = 3  # Todo: explain this parameter; why would it fail to forecast if data is there for the full day?

    # The failed test model (this failure enqueues a new job)
    create_forecasting_jobs(
        timed_value_type="Power",
        start_of_roll=as_server_time(datetime(2015, 1, 1, hour_start)),
        end_of_roll=as_server_time(datetime(2015, 1, 1, hour_start + 2)),
        horizons=[horizon],
        asset_id=solar_device1.id,
        model_search_term=model_to_start_with,
        custom_model_params=cmp,
    )
    work_on_rq(app.queues["forecasting"], exc_handler=handle_forecasting_exception)

    # Check if the correct model failed in the expected way
    check_failures(
        app.queues["forecasting"],
        ["NotEnoughDataException"],
        ["%s model v%d" % (model_to_start_with, model_version)],
    )

    # this query is useful to check data:
    def make_query(the_horizon_hours: int) -> Query:
        the_horizon = timedelta(hours=the_horizon_hours)
        return (
            Power.query.filter(Power.asset_id == solar_device1.id)
            .filter(Power.horizon == the_horizon)
            .filter(
                (
                    Power.datetime
                    >= as_server_time(
                        datetime(2015, 1, 1, hour_start + the_horizon_hours)
                    )
                )
                & (
                    Power.datetime
                    < as_server_time(
                        datetime(2015, 1, 1, hour_start + the_horizon_hours + 2)
                    )
                )
            )
        )

    # The successful (linear or naive) OLS leads to these.
    forecasts = make_query(the_horizon_hours=horizon_hours).all()

    assert len(forecasts) == 8
    check_aggregate(8, horizon)

    if model_to_start_with == "linear-OLS":
        existing_data = make_query(the_horizon_hours=0).all()

        for ed, fd in zip(existing_data, forecasts):
            assert ed.value == fd.value

    # Now to check which models actually got to work.
    # We check which data sources do and do not exist by now:
    assert (
        get_data_source("failing-test model v1") is None
    )  # the test failure model failed -> no data source
    if model_to_start_with == "linear-OLS":
        assert (
            get_data_source() is None
        )  # the default (linear regression) (was made to) fail, as well
        assert (
            get_data_source("naive model v1") is not None
        )  # the naive one had to be used
    else:
        assert get_data_source() is not None  # the default (linear regression)
        assert (
            get_data_source("naive model v1") is None
        )  # the naive one did not have to be used
