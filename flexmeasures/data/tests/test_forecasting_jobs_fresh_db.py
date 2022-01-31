from datetime import timedelta, datetime

import pytest
from sqlalchemy.orm import Query

from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.data.services.forecasting import (
    create_forecasting_jobs,
    handle_forecasting_exception,
)
from flexmeasures.data.tests.test_forecasting_jobs import (
    custom_model_params,
    check_aggregate,
    check_failures,
    get_data_source,
)
from flexmeasures.data.tests.utils import work_on_rq
from flexmeasures.utils.time_utils import as_server_time


def test_forecasting_three_hours_of_wind(app, setup_fresh_test_data, clean_redis):
    wind_device2: Sensor = Sensor.query.filter_by(name="wind-asset-2").one_or_none()

    # makes 12 forecasts
    horizon = timedelta(hours=1)
    job = create_forecasting_jobs(
        start_of_roll=as_server_time(datetime(2015, 1, 1, 10)),
        end_of_roll=as_server_time(datetime(2015, 1, 1, 13)),
        horizons=[horizon],
        sensor_id=wind_device2.id,
        custom_model_params=custom_model_params(),
    )
    print("Job: %s" % job[0].id)

    work_on_rq(app.queues["forecasting"], exc_handler=handle_forecasting_exception)

    forecasts = (
        TimedBelief.query.filter(TimedBelief.sensor_id == wind_device2.id)
        .filter(TimedBelief.belief_horizon == horizon)
        .filter(
            (TimedBelief.event_start >= as_server_time(datetime(2015, 1, 1, 11)))
            & (TimedBelief.event_start < as_server_time(datetime(2015, 1, 1, 14)))
        )
        .all()
    )
    assert len(forecasts) == 12
    check_aggregate(12, horizon, wind_device2.id)


def test_forecasting_two_hours_of_solar(app, setup_fresh_test_data, clean_redis):
    solar_device1: Sensor = Sensor.query.filter_by(name="solar-asset-1").one_or_none()
    wind_device2: Sensor = Sensor.query.filter_by(name="wind-asset-2").one_or_none()
    print(solar_device1)
    print(wind_device2)

    # makes 8 forecasts
    horizon = timedelta(hours=1)
    job = create_forecasting_jobs(
        start_of_roll=as_server_time(datetime(2015, 1, 1, 12)),
        end_of_roll=as_server_time(datetime(2015, 1, 1, 14)),
        horizons=[horizon],
        sensor_id=solar_device1.id,
        custom_model_params=custom_model_params(),
    )
    print("Job: %s" % job[0].id)

    work_on_rq(app.queues["forecasting"], exc_handler=handle_forecasting_exception)
    forecasts = (
        TimedBelief.query.filter(TimedBelief.sensor_id == solar_device1.id)
        .filter(TimedBelief.belief_horizon == horizon)
        .filter(
            (TimedBelief.event_start >= as_server_time(datetime(2015, 1, 1, 13)))
            & (TimedBelief.event_start < as_server_time(datetime(2015, 1, 1, 15)))
        )
        .all()
    )
    assert len(forecasts) == 8
    check_aggregate(8, horizon, solar_device1.id)


@pytest.mark.parametrize(
    "model_to_start_with, model_version", [("failing-test", 1), ("linear-OLS", 2)]
)
def test_failed_model_with_too_much_training_then_succeed_with_fallback(
    setup_fresh_test_data, app, clean_redis, model_to_start_with, model_version
):
    """
    Here we fail once - because we start with a model that needs too much training.
    So we check for this failure happening as expected.
    But then, we do succeed with the fallback model one level down.
    (fail-test falls back to linear & linear falls back to naive).
    As a result, there should be forecasts in the DB.
    """
    solar_device1: Sensor = Sensor.query.filter_by(name="solar-asset-1").one_or_none()
    horizon_hours = 1
    horizon = timedelta(hours=horizon_hours)

    cmp = custom_model_params()
    hour_start = 5
    if model_to_start_with == "linear-OLS":
        # making the linear model fail and fall back to naive
        hour_start = 3  # Todo: explain this parameter; why would it fail to forecast if data is there for the full day?

    # The failed test model (this failure enqueues a new job)
    create_forecasting_jobs(
        start_of_roll=as_server_time(datetime(2015, 1, 1, hour_start)),
        end_of_roll=as_server_time(datetime(2015, 1, 1, hour_start + 2)),
        horizons=[horizon],
        sensor_id=solar_device1.id,
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
            TimedBelief.query.filter(TimedBelief.sensor_id == solar_device1.id)
            .filter(TimedBelief.belief_horizon == the_horizon)
            .filter(
                (
                    TimedBelief.event_start
                    >= as_server_time(
                        datetime(2015, 1, 1, hour_start + the_horizon_hours)
                    )
                )
                & (
                    TimedBelief.event_start
                    < as_server_time(
                        datetime(2015, 1, 1, hour_start + the_horizon_hours + 2)
                    )
                )
            )
        )

    # The successful (linear or naive) OLS leads to these.
    forecasts = make_query(the_horizon_hours=horizon_hours).all()

    assert len(forecasts) == 8
    check_aggregate(8, horizon, solar_device1.id)

    if model_to_start_with == "linear-OLS":
        existing_data = make_query(the_horizon_hours=0).all()

        for ed, fd in zip(existing_data, forecasts):
            assert ed.event_value == fd.event_value

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
