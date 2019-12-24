from typing import Tuple, List, Union
from datetime import datetime, timedelta


from bvp.data.models.forecasting.exceptions import NotEnoughDataException
from bvp.utils.time_utils import as_bvp_time


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
    oldest_value = q.order_by(generic_asset_value_class.datetime.asc()).first()
    newest_value = q.order_by(generic_asset_value_class.datetime.desc()).first()
    if oldest_value is None:
        raise NotEnoughDataException(
            "No data available at all. Forecasting impossible."
        )
    if query_window[0] < oldest_value.datetime:
        suggested_start = forecast_start + (oldest_value.datetime - query_window[0])
        raise NotEnoughDataException(
            "Not enough data to forecast %s for the forecast window %s to %s: set start date to %s ?"
            % (
                generic_asset.name,
                as_bvp_time(query_window[0]),
                as_bvp_time(query_window[1]),
                as_bvp_time(suggested_start),
            )
        )
    if query_window[1] - horizon > newest_value.datetime + timedelta(
        minutes=15
    ):  # Todo: resolution should come from generic asset
        suggested_end = forecast_end + (
            newest_value.datetime - (query_window[1] - horizon)
        )
        raise NotEnoughDataException(
            "Not enough data to forecast %s for the forecast window %s to %s: set end date to %s ?"
            % (
                generic_asset.name,
                as_bvp_time(query_window[0]),
                as_bvp_time(query_window[1]),
                as_bvp_time(suggested_end),
            )
        )


def create_lags(
    n_lags: int, generic_asset_type: str, horizon: timedelta, resolution: timedelta
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
    if hasattr(generic_asset_type, "daily_seasonality"):
        if generic_asset_type.daily_seasonality:
            lag_period = timedelta(days=1)
            number_of_nan_lags = 1 + (horizon - resolution) // lag_period
            for L in range(n_lags):
                lags.append((L + number_of_nan_lags) * lag_period)

    # Remove possible double entries
    return list(set(lags))


def get_query_window(
    training_start: datetime, end: datetime, lags: List[timedelta]
) -> Tuple[datetime, datetime]:
    """Derive query window from start and end date, as well as lags (if any).
    This makes sure we have enough data for lagging and forecasting."""
    if not lags:
        query_start = training_start
    else:
        query_start = training_start - max(lags)
    query_end = end
    return query_start, query_end


def set_training_and_testing_dates(
    start: datetime,
    training_and_testing_period: Union[timedelta, Tuple[datetime, datetime]],
    horizon: timedelta,
) -> Tuple[datetime, datetime]:
    """If needed (if training_and_testing_period is a timedelta),
    derive training_start and testing_end by start and horizon,
    otherwise simply return training_and_testing_period."""
    if isinstance(training_and_testing_period, timedelta):
        return start - training_and_testing_period - horizon, start - horizon
    else:
        return training_and_testing_period
