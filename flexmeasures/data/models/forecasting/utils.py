from typing import Tuple, List, Union
from datetime import datetime, timedelta

from flexmeasures.data.config import db
from flexmeasures.data.models.forecasting.exceptions import NotEnoughDataException
from flexmeasures.utils.time_utils import as_server_time


def check_data_availability(
    generic_asset,
    generic_asset_value_class,
    forecast_start: datetime,
    forecast_end: datetime,
    query_window: Tuple[datetime, datetime],
    horizon: timedelta,
):
    """Check if enough data is available in the database in the first place,
    for training window and lagged variables. Otherwise, suggest new forecast period.
    TODO: we could also check regressor data, if we get regressor specs passed in here.
    """
    q = generic_asset_value_class.query.join(generic_asset.__class__).filter(
        generic_asset.__class__.name == generic_asset.name
    )
    first_value = q.order_by(generic_asset_value_class.datetime.asc()).first()
    last_value = q.order_by(generic_asset_value_class.datetime.desc()).first()
    if first_value is None:
        raise NotEnoughDataException(
            "No data available at all. Forecasting impossible."
        )
    first = as_server_time(first_value.datetime)
    last = as_server_time(last_value.datetime)
    if query_window[0] < first:
        suggested_start = forecast_start + (first - query_window[0])
        raise NotEnoughDataException(
            f"Not enough data to forecast {generic_asset.name} "
            f"for the forecast window {as_server_time(forecast_start)} to {as_server_time(forecast_end)}. "
            f"I needed to query from {as_server_time(query_window[0])}, "
            f"but the first value available is from {first} to {first + generic_asset.event_resolution}. "
            f"Consider setting the start date to {as_server_time(suggested_start)}."
        )
    if query_window[1] - horizon > last + generic_asset.event_resolution:
        suggested_end = forecast_end + (last - (query_window[1] - horizon))
        raise NotEnoughDataException(
            f"Not enough data to forecast {generic_asset.name} "
            f"for the forecast window {as_server_time(forecast_start)} to {as_server_time(forecast_end)}. "
            f"I needed to query until {as_server_time(query_window[1] - horizon)}, "
            f"but the last value available is from {last} to {last + generic_asset.event_resolution}. "
            f"Consider setting the end date to {as_server_time(suggested_end)}."
        )


def create_lags(
    n_lags: int,
    generic_asset_type: db.Model,
    horizon: timedelta,
    resolution: timedelta,
    use_periodicity: bool,
) -> List[timedelta]:
    """ List the lags for this asset type, using horizon and resolution information."""
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
    if use_periodicity and hasattr(generic_asset_type, "daily_seasonality"):
        if generic_asset_type.daily_seasonality:
            lag_period = timedelta(days=1)
            number_of_nan_lags = 1 + (horizon - resolution) // lag_period
            for L in range(n_lags):
                lags.append((L + number_of_nan_lags) * lag_period)

    # Remove possible double entries
    return list(set(lags))


def get_query_window(
    training_start: datetime, forecast_end: datetime, lags: List[timedelta]
) -> Tuple[datetime, datetime]:
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
    training_and_testing_period: Union[timedelta, Tuple[datetime, datetime]],
) -> Tuple[datetime, datetime]:
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
