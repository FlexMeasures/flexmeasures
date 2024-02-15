from __future__ import annotations

from datetime import datetime, timedelta
from sqlalchemy import select

from flexmeasures.data import db
from flexmeasures.data.models.forecasting.exceptions import NotEnoughDataException
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.utils.time_utils import as_server_time


def check_data_availability(
    old_sensor_model,
    old_time_series_data_model,
    forecast_start: datetime,
    forecast_end: datetime,
    query_window: tuple[datetime, datetime],
    horizon: timedelta,
):
    """Check if enough data is available in the database in the first place,
    for training window and lagged variables. Otherwise, suggest new forecast period.
    TODO: we could also check regressor data, if we get regressor specs passed in here.
    """
    q = (
        select(old_time_series_data_model)
        .join(old_sensor_model.__class__)
        .filter(old_sensor_model.__class__.name == old_sensor_model.name)
    )
    first_value = db.session.scalars(
        q.order_by(old_time_series_data_model.event_start.asc()).limit(1)
    ).first()
    last_value = db.session.scalars(
        q.order_by(old_time_series_data_model.event_start.desc()).limit(1)
    ).first()
    if first_value is None:
        raise NotEnoughDataException(
            "No data available at all. Forecasting impossible."
        )
    first = as_server_time(first_value.event_start)
    last = as_server_time(last_value.event_start)
    if query_window[0] < first:
        suggested_start = forecast_start + (first - query_window[0])
        raise NotEnoughDataException(
            f"Not enough data to forecast {old_sensor_model.name} "
            f"for the forecast window {as_server_time(forecast_start)} to {as_server_time(forecast_end)}. "
            f"I needed to query from {as_server_time(query_window[0])}, "
            f"but the first value available is from {first} to {first + old_sensor_model.event_resolution}. "
            f"Consider setting the start date to {as_server_time(suggested_start)}."
        )
    if query_window[1] - horizon > last + old_sensor_model.event_resolution:
        suggested_end = forecast_end + (last - (query_window[1] - horizon))
        raise NotEnoughDataException(
            f"Not enough data to forecast {old_sensor_model.name} "
            f"for the forecast window {as_server_time(forecast_start)} to {as_server_time(forecast_end)}. "
            f"I needed to query until {as_server_time(query_window[1] - horizon)}, "
            f"but the last value available is from {last} to {last + old_sensor_model.event_resolution}. "
            f"Consider setting the end date to {as_server_time(suggested_end)}."
        )


def create_lags(
    n_lags: int,
    sensor: Sensor,
    horizon: timedelta,
    resolution: timedelta,
    use_periodicity: bool,
) -> list[timedelta]:
    """List the lags for this asset type, using horizon and resolution information."""
    lags = []

    # Include a zero lag in case of backwards forecasting
    # Todo: we should always take into account the latest forecast, so always append the zero lag if that belief exists
    if horizon < timedelta(hours=0):
        lags.append(timedelta(hours=0))

    # Include latest measurements
    lag_period = resolution
    number_of_nan_lags = 1 + (horizon - resolution) // lag_period
    for L in range(n_lags):
        lags.append((L + number_of_nan_lags) * lag_period)

    # Include relevant measurements given the asset's periodicity
    if use_periodicity and sensor.get_attribute("daily_seasonality"):
        lag_period = timedelta(days=1)
        number_of_nan_lags = 1 + (horizon - resolution) // lag_period
        for L in range(n_lags):
            lags.append((L + number_of_nan_lags) * lag_period)

    # Remove possible double entries
    return list(set(lags))


def get_query_window(
    training_start: datetime, forecast_end: datetime, lags: list[timedelta]
) -> tuple[datetime, datetime]:
    """Derive query window from start and end date, as well as lags (if any).
    This makes sure we have enough data for lagging and forecasting."""
    if not lags:
        query_start = training_start
    else:
        query_start = training_start - max(lags)
    query_end = forecast_end
    return query_start, query_end


def set_training_and_testing_dates(
    forecast_start: datetime,
    training_and_testing_period: timedelta | tuple[datetime, datetime],
) -> tuple[datetime, datetime]:
    """If needed (if training_and_testing_period is a timedelta),
    derive training_start and testing_end from forecasting_start,
    otherwise simply return training_and_testing_period.


        |------forecast_horizon/belief_horizon------|
        |                  |-------resolution-------|
        belief_time        event_start      event_end


                           |--resolution--|--resolution--|--resolution--|--resolution--|--resolution--|--resolution--|
        |---------forecast_horizon--------|              |              |              |              |              |
        belief_time        event_start    |              |              |              |              |              |
                       |---------forecast_horizon--------|              |              |              |              |
                       belief_time        event_start    |              |              |              |              |
                           |          |---------forecast_horizon--------|              |              |              |
                           |          belief_time        event_start    |              |              |              |
    |--------max_lag-------|--------training_and_testing_period---------|---------------forecast_period--------------|
    query_start            training_start |              |    testing_end/forecast_start              |   forecast_end
        |------min_lag-----|              |          |---------forecast_horizon--------|              |              |
                           |              |          belief_time        event_start    |              |              |
                           |              |              |          |---------forecast_horizon--------|              |
                           |              |              |          belief_time        event_start    |              |
                           |              |              |              |          |---------forecast_horizon--------|
                           |              |              |              |          belief_time        event_start    |
    |--------------------------------------------------query_window--------------------------------------------------|

    """
    if isinstance(training_and_testing_period, timedelta):
        return forecast_start - training_and_testing_period, forecast_start
    else:
        return training_and_testing_period
