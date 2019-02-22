from datetime import timedelta

from bvp.data.models.forecasting import NotEnoughDataException


def check_data_availability(
    generic_asset,
    generic_asset_value_class,
    forecast_start,
    forecast_end,
    query_window,
    horizon,
):
    """Check if enough data is available in the database in the first place,
     for training window and lagged variables. Otherwise, suggest new forecast period."""
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
            "Not enough data to forecast %s for this forecast window %s to %s: set start date to %s ?"
            % (generic_asset.name, query_window[0], query_window[1], suggested_start)
        )
    if query_window[1] - horizon > newest_value.datetime + timedelta(
        minutes=15
    ):  # Todo: resolution should come from generic asset
        suggested_end = forecast_end + (
            newest_value.datetime - (query_window[1] - horizon)
        )
        raise NotEnoughDataException(
            "Not enough data to forecast %s for the forecast window %s to %s: set end date to %s ?"
            % (generic_asset.name, query_window[0], query_window[1], suggested_end)
        )
