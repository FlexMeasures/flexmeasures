"""
Generic services for accessing data.
"""

from typing import List, Dict, Tuple, Union, Callable
from datetime import datetime
from inflection import pluralize

from flask import session
from flask_security.core import current_user
import pandas as pd
from sqlalchemy.orm.query import Query

from bvp.data.models.assets import AssetType, Asset, Power
from bvp.data.models.markets import Market, Price
from bvp.data.models.weather import WeatherSensor, Weather
from bvp.utils import time_utils
from bvp.data.config import db


def get_assets() -> List[Asset]:
    """Return a list of all Asset objects of current_user (or all for admins).
    The asset list is constructed lazily (only once per app start)."""
    if current_user.is_authenticated:
        if current_user.has_role("admin"):
            assets = Asset.query.order_by(Asset.id.desc()).all()
        else:
            assets = (
                Asset.query.filter_by(owner=current_user)
                .order_by(Asset.id.desc())
                .all()
            )
        return assets
    return []


def get_asset_groups() -> Dict[str, Query]:
    """
    An asset group is defined by Asset queries. Each query has a name, and we prefer pluralised names.
    They still need a executive call, like all(), count() or first()
    """
    # 1. Custom asset groups by combinations of asset types
    asset_queries = dict(
        renewables=(Asset.query.filter(Asset.asset_type_name.in_(["solar", "wind"])))
    )
    # 2. We also include a group per asset type - using the pluralised asset type name
    for asset_type in AssetType.query.all():
        asset_queries[pluralize(asset_type.name)] = Asset.query.filter_by(
            asset_type_name=asset_type.name
        )

    if current_user.is_authenticated and not current_user.has_role("admin"):
        for name, query in asset_queries.items():
            asset_queries[name] = query.filter_by(owner=current_user)

    return asset_queries


def get_power(
    asset_names: List[str],
    start: datetime = None,
    end: datetime = None,
    resolution: str = None,
    sum_multiple=True,
    create_if_empty=False,
) -> Union[pd.DataFrame, Dict[str, pd.DataFrame]]:
    # TODO: check if asset names are all valid?
    def make_query(
        asset_name: str, query_start: datetime, query_end: datetime
    ) -> Query:
        return (
            db.session.query(Power.datetime, Power.value)
            .join(Asset)
            .filter(Asset.name == asset_name)
            .filter((Power.datetime >= query_start) & (Power.datetime <= query_end))
        )

    return _get_time_series_data(
        data_sources=asset_names,
        make_query=make_query,
        start=start,
        end=end,
        resolution=resolution,
        sum_multiple=sum_multiple,
        create_if_empty=create_if_empty,
    )


def get_prices(
    market_names: List[str],
    start: datetime = None,
    end: datetime = None,
    resolution: str = None,
    sum_multiple=True,
    create_if_empty=False,
) -> Union[pd.DataFrame, Dict[str, pd.DataFrame]]:
    # TODO: check if market names are all valid?
    def make_query(
        market_name: str, query_start: datetime, query_end: datetime
    ) -> Query:
        return (
            db.session.query(Price.datetime, Price.value)
            .join(Market)
            .filter(Market.name == market_name)
            .filter((Price.datetime >= query_start) & (Price.datetime <= query_end))
        )

    return _get_time_series_data(
        data_sources=market_names,
        make_query=make_query,
        start=start,
        end=end,
        resolution=resolution,
        sum_multiple=sum_multiple,
        create_if_empty=create_if_empty,
    )


def get_weather(
    sensor_names: List[str],
    start: datetime = None,
    end: datetime = None,
    resolution: str = None,
    sum_multiple=True,
    create_if_empty=False,
) -> Union[pd.DataFrame, Dict[str, pd.DataFrame]]:
    # TODO: check if sensor names are all valid?
    # TODO: move query creation as util method to the model class?
    def make_query(
        sensor_name: str, query_start: datetime, query_end: datetime
    ) -> Query:
        return (
            db.session.query(Weather.datetime, Weather.value)
            .join(WeatherSensor)
            .filter(WeatherSensor.name == sensor_name)
            .filter((Weather.datetime >= query_start) & (Weather.datetime <= query_end))
        )

    return _get_time_series_data(
        data_sources=sensor_names,
        make_query=make_query,
        start=start,
        end=end,
        resolution=resolution,
        sum_multiple=sum_multiple,
        create_if_empty=create_if_empty,
    )


def _get_time_series_data(
    data_sources: List[str],
    make_query: Callable[[str, datetime, datetime], Query],
    start: datetime = None,
    end: datetime = None,
    resolution: str = None,
    sum_multiple: bool = True,
    create_if_empty: bool = False,
) -> Union[pd.DataFrame, Dict[str, pd.DataFrame]]:
    """Get time series data from one or more sources and rescale and re-package it to order.

    We can (lazily) look up by pickle, or load from the database.
    In the latter case, we are relying on time series data (power measurements and prices at this point) to
    have the same relevant column names (datetime, value).
    We require a list of asset or market names to find the source.
    If the time range parameters are None, they will be gotten from the session.
    Response is a 2D data frame with the usual columns (y, yhat, ...).
    If data from multiple assets is retrieved, the results are being summed.
    Or, if sum_multiple is False, the response will be a dictionary with asset names
    as keys and data frames as values.
    The response might be an empty data frame if no data exists for these assets
    in this time range.
    If an empty data frame would be returned, but create_if_empty is True, then
    a new DataFrame with the correct datetime index but zeroes as content is returned.
    """
    data_as_dict: Dict[str, pd.DataFrame] = {}
    data_as_df: pd.DataFrame() = pd.DataFrame()

    start, end, resolution = ensure_timing_vars_are_set(start, end, resolution)

    for data_source in data_sources:

        values = query_time_series_data(
            data_source, make_query, start, end, resolution, create_if_empty
        )

        # Here we only build one data frame, summed up if necessary.
        if sum_multiple is True:
            if data_as_df.empty:
                data_as_df = values
            elif not values.empty:
                data_as_df = data_as_df.add(values)
        else:  # Here we build a dict with data frames.
            if len(data_as_dict.keys()) == 0:
                data_as_dict = {data_source: values}
            else:
                data_as_dict[data_source] = values

    if sum_multiple is True:
        return data_as_df
    else:
        return data_as_dict


def query_time_series_data(
    data_source: str,
    make_query: Callable[[str, datetime, datetime], Query],
    start: datetime = None,
    end: datetime = None,
    resolution: str = None,
    create_if_empty: bool = False,
) -> pd.DataFrame:
    """
    Run a query for time series data on the database.
    Here, we need to know that postgres only stores naive datetimes and we keep them as UTC.
    Therefore, we localize the result.
    Then, we resample the result, to fit the given resolution.
    If wanted, we can create a DataFrame with zeroes if no results were found in the database.
    Returns a DataFrame with a "y" column.
    """
    query = make_query(data_source, start, end)
    values_orig = pd.read_sql(
        query.statement, db.session.bind, parse_dates=["datetime"]
    )
    values_orig.rename(index=str, columns={"value": "y"}, inplace=True)
    values_orig.set_index("datetime", drop=True, inplace=True)
    if values_orig.index.tzinfo is None:
        values_orig.index = values_orig.index.tz_localize(time_utils.get_timezone())
    else:
        values_orig.index = values_orig.index.tz_convert(time_utils.get_timezone())

    # re-sample data to the resolution we need to serve
    values = values_orig.resample(resolution).mean()

    # make zero-based result if no values were found
    if values.empty and create_if_empty:
        time_steps = pd.date_range(
            start, end, freq=resolution, tz=time_utils.get_timezone()
        )
        values = pd.DataFrame(index=time_steps, columns=["y"]).fillna(0.)

    return values


def ensure_timing_vars_are_set(
    start: datetime, end: datetime, resolution: str
) -> Tuple[datetime, datetime, str]:
    if (
        start is None
        or end is None
        or (resolution is None and "resolution" not in session)
    ):
        time_utils.set_time_range_for_session()
        start = session["start_time"]
        end = session["end_time"]
        resolution = session["resolution"]

    return start, end, resolution


def extract_forecasts(df: pd.DataFrame) -> pd.DataFrame:
    """
    Extract forecast columns (given the chosen horizon) and give them the standard naming.
    Returns an empty DataFrame if the expected forecast columns don't exist.
    """
    forecast_columns = [
        "yhat",
        "yhat_upper",
        "yhat_lower",
    ]  # this is what the plotter expects
    horizon = session["forecast_horizon"]
    forecast_renaming = {
        "yhat_%s" % horizon: "yhat",
        "yhat_%s_upper" % horizon: "yhat_upper",
        "yhat_%s_lower" % horizon: "yhat_lower",
    }
    if "yhat_%s" % horizon not in df.columns:
        return pd.DataFrame()
    return df.rename(forecast_renaming, axis="columns")[forecast_columns]


class Resource:
    """
    This class represents a resource and helps to map names to assets.
    A "resource" is an umbrella term:

    * It can be one asset / market.
    * It can be a group of assets / markets. (see get_asset_groups)

    The class itself defines only one thing: a resource name.
    The class methods provide helpful functions to get from resource name to assets and their time series data.

    Typical usages might thus be:

    * Resource(session["resource"]).assets
    * Resource(session["resource"]).display_name
    * Resource(session["resource"]).get_data()

    TODO: The link to markets still needs some care (best to do that once we have modeled markets better)
          First, decide, if we want to call markets a "Resource". If so, get_data, should maybe just decide which data
          to fetch. I cannot imagine we ever want to mix data from assets and markets.
    """

    last_loaded_asset_list = []  # this can be used to avoid loading assets more than once during one call stack

    def __init__(self, name):
        if name is None or name == "":
            raise Exception("Empty resource name passed (%s)" % name)
        self.name = name

    @property
    def assets(self) -> List[Asset]:
        """Gather assets which are identified by this resource's name.
        The resource name is either the name of an asset group or an individual asset."""
        assets = []
        asset_groups = get_asset_groups()
        if self.name in asset_groups:
            for asset in asset_groups[self.name]:
                assets.append(asset)
        else:
            asset = Asset.query.filter_by(name=self.name).one_or_none()
            if asset is not None:
                assets = [asset]
        self.last_loaded_asset_list = assets
        return assets

    @property
    def is_unique_asset(self) -> bool:
        """Determines whether the resource represents a unique asset."""
        return [self.name] == [a.name for a in self.assets]

    @property
    def display_name(self) -> str:
        """Attempt to get a beautiful name to show if possible."""
        if self.is_unique_asset:
            return self.assets[0].display_name
        return self.name

    @property
    def unique_asset_type_names(self) -> List[str]:
        """Return list of unique asset types represented by this resource."""
        return list(
            set([a.asset_type.name for a in self.assets])
        )  # list of unique asset type names in resource

    def get_data(
        self,
        start: datetime = None,
        end: datetime = None,
        resolution: str = None,
        sum_multiple: bool = True,
    ) -> Union[pd.DataFrame, Dict[str, pd.DataFrame]]:
        """Get data for one or more assets.
        If the time range parameters are None, they will be gotten from the session.
        See get_power for more information."""
        asset_names = []
        for asset in self.assets:
            asset_names.append(asset.name)
        data = get_power(asset_names, start, end, resolution, sum_multiple=sum_multiple)
        return data
