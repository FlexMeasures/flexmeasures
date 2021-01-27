"""
Generic services for accessing asset data.
"""

from __future__ import annotations
from functools import cached_property, wraps
from typing import List, Dict, Tuple, Type, TypeVar, Union, Optional
from datetime import datetime
from flexmeasures.utils.flexmeasures_inflection import parameterize, pluralize
from itertools import groupby

from flask_security.core import current_user
import inflect
import pandas as pd
from sqlalchemy.orm import Query, Session
import timely_beliefs as tb

from flexmeasures.data.models.assets import (
    AssetType,
    Asset,
    Power,
    assets_share_location,
)
from flexmeasures.data.models.markets import Market, Price
from flexmeasures.data.models.weather import Weather, WeatherSensor, WeatherSensorType
from flexmeasures.data.models.user import User
from flexmeasures.data.queries.utils import simplify_index, parse_sqlalchemy_results
from flexmeasures.data.services.time_series import aggregate_values
from flexmeasures.utils.geo_utils import parse_lat_lng
from flexmeasures.utils import coding_utils, time_utils


p = inflect.engine()
cached_property = coding_utils.make_registering_decorator(cached_property)
SensorType = TypeVar("SensorType", Type[Power], Type[Price], Type[Weather])


def get_markets() -> List[Market]:
    """Return a list of all Market objects."""
    return Market.query.order_by(Market.name.asc()).all()


def get_assets(
    owner_id: Optional[int] = None,
    order_by_asset_attribute: str = "id",
    order_direction: str = "desc",
) -> List[Asset]:
    """Return a list of all Asset objects owned by current_user
    (or all users or a specific user - for this, admins can set an owner_id).
    """
    return _build_asset_query(owner_id, order_by_asset_attribute, order_direction).all()


def has_assets(owner_id: Optional[int] = None) -> bool:
    """Return True if the current user owns any assets.
    (or all users or a specific user - for this, admins can set an owner_id).
    """
    return _build_asset_query(owner_id).count() > 0


def can_access_asset(asset: Asset) -> bool:
    """Return True if the current user is an admin or the owner of the asset:"""
    if current_user.is_authenticated:
        if current_user.has_role("admin"):
            return True
        if asset.owner == current_user:
            return True
    return False


def _build_asset_query(
    owner_id: Optional[int] = None,
    order_by_asset_attribute: str = "id",
    order_direction: str = "desc",
) -> Query:
    """Build an Asset query. Only authenticated users can use this.
    Admins can query for all assets (owner_id is None) or for any user (the asset's owner).
    Non-admins can only query for themselves (owner_id is ignored).

    order_direction can be "asc" or "desc".
    """
    if current_user.is_authenticated:
        if current_user.has_role("admin"):
            if owner_id is not None:
                if not isinstance(owner_id, int):
                    try:
                        owner_id = int(owner_id)
                    except TypeError:
                        raise Exception(
                            "Owner id %s cannot be parsed as integer, thus seems to be invalid."
                            % owner_id
                        )
                query = Asset.query.filter(Asset.owner_id == owner_id)
            else:
                query = Asset.query
        else:
            query = Asset.query.filter_by(owner=current_user)
    else:
        query = Asset.query.filter(Asset.owner_id == -1)
    query = query.order_by(
        getattr(getattr(Asset, order_by_asset_attribute), order_direction)()
    )
    return query


def get_asset_group_queries(
    custom_additional_groups: Optional[List[str]] = None,
    all_users: bool = False,
) -> Dict[str, Query]:
    """
    An asset group is defined by Asset queries. Each query has a name, and we prefer pluralised display names.
    They still need an executive call, like all(), count() or first().

    :param custom_additional_groups: list of additional groups next to groups that represent unique asset types.
                                     Valid names are:
                                     - "renewables", to query all solar and wind assets
                                     - "EVSE", to query all Electric Vehicle Supply Equipment
                                     - "each Charge Point", to query each individual Charge Point
                                                            (i.e. all EVSE at 1 location)
    :param all_users: if True, do not filter out assets that do not belong to the user (use with care)
    """

    if custom_additional_groups is None:
        custom_additional_groups = []
    asset_queries = {}

    # 1. Custom asset groups by combinations of asset types
    if "renewables" in custom_additional_groups:
        asset_queries["renewables"] = Asset.query.filter(
            Asset.asset_type_name.in_(["solar", "wind"])
        )
    if "EVSE" in custom_additional_groups:
        asset_queries["EVSE"] = Asset.query.filter(
            Asset.asset_type_name.in_(["one-way_evse", "two-way_evse"])
        )

    # 2. We also include a group per asset type - using the pluralised asset type display name
    for asset_type in AssetType.query.all():
        asset_queries[pluralize(asset_type.display_name)] = Asset.query.filter_by(
            asset_type_name=asset_type.name
        )

    if not all_users:
        asset_queries = mask_inaccessible_assets(asset_queries)

    # 3. We group EVSE assets by location (if they share a location, they belong to the same Charge Point)
    if "each Charge Point" in custom_additional_groups:
        asset_queries.update(get_charge_point_queries())

    return asset_queries


def get_charge_point_queries() -> Dict[str, Query]:
    """
    A Charge Point is defined similarly to asset groups (see get_asset_group_queries).
    We group EVSE assets by location (if they share a location, they belong to the same Charge Point)
    Like get_asset_group_queries, the values in the returned dict still need an executive call, like all(), count() or first().

    The Charge Points are named on the basis of the first EVSE in their list,
    using either the whole EVSE display name or that part that comes before a " -" delimiter. For example:
    If:
        evse_display_name = "Seoul Hilton - charger 1"
    Then:
        charge_point_display_name = "Seoul Hilton (Charge Point)"
    """
    asset_queries = {}
    all_evse_assets = Asset.query.filter(
        Asset.asset_type_name.in_(["one-way_evse", "two-way_evse"])
    ).all()
    cp_groups = group_assets_by_location(all_evse_assets)
    for cp_group in cp_groups:
        charge_point_name = cp_group[0].display_name.split(" -")[0] + " (Charge Point)"
        asset_queries[charge_point_name] = Asset.query.filter(
            Asset.name.in_([evse.name for evse in cp_group])
        )
    return mask_inaccessible_assets(asset_queries)


def mask_inaccessible_assets(
    asset_queries: Union[Query, Dict[str, Query]]
) -> Union[Query, Dict[str, Query]]:
    """Filter out any assets that the user should not be able to access.

    We do not explicitly check user authentication here, because non-authenticated users are not admins
    and have no asset ownership, so applying this filter for non-admins masks all assets.
    """
    if not current_user.has_role("admin"):
        if isinstance(asset_queries, dict):
            for name, query in asset_queries.items():
                asset_queries[name] = query.filter_by(owner=current_user)
        else:
            asset_queries = asset_queries.filter_by(owner=current_user)
    return asset_queries


def get_center_location(db: Session, user: Optional[User]) -> Tuple[float, float]:
    """
    Find the center position between all assets.
    If user is passed and not admin then we only consider assets
    owned by the user.
    TODO: if we introduce accounts, this logic should look for these assets.
    """
    query = (
        "Select (min(latitude) + max(latitude)) / 2 as latitude,"
        " (min(longitude) + max(longitude)) / 2 as longitude"
        " from asset"
    )
    if user and not user.has_role("admin"):
        query += f" where owner_id = {user.id}"
    locations: List[dict] = parse_sqlalchemy_results(
        db.session.execute(query + ";").fetchall()
    )
    if (
        len(locations) == 0
        or locations[0]["latitude"] is None
        or locations[0]["longitude"] is None
    ):
        return (52.38, 4.88)  # Amsterdam, NL
    return locations[0]["latitude"], locations[0]["longitude"]


def check_cache(attribute):
    """Decorator for Resource class attributes to check if the resource has cached the attribute.

    Example usage:
    @check_cache("cached_data")
    def some_property(self):
        return self.cached_data
    """

    def inner_function(fn):
        @wraps(fn)
        def wrapper(self, *args, **kwargs):
            if not hasattr(self, attribute) or not getattr(self, attribute):
                raise ValueError(
                    "Resource has no cached data. Call resource.load_sensor_data() first."
                )
            return fn(self, *args, **kwargs)

        return wrapper

    return inner_function


class Resource:
    """
    This class represents a group of assets of the same type, and provides
    helpful functions to retrieve their time series data and derived statistics.

    Resolving asset type names
    --------------------------
    When initialised with a plural asset type name, the resource will contain all assets of
    the given type that are accessible to the user.
    When initialised with just one asset name, the resource will list only that asset.

    Loading structure
    -----------------
    Initialization only loads structural information from the database (which assets the resource groups).

    Loading and caching time series
    -------------------------------
    To load time series data for a certain time window, use the load_sensor_data() method.
    This loads beliefs data from the database and caches the results (as a named attribute).
    Caches are cleared when new time series data is loaded (or when the Resource instance seizes to exist).

    Loading and caching derived statistics
    --------------------------------------
    Cached time series data is used to compute derived statistics, such as aggregates and scores.
    More specifically:
    - demand and supply
    - aggregated values (summed over assets)
    - total values (summed over time)
    - mean values (averaged over time) (todo: add this property)
    - revenue and cost
    - profit/loss
    When a derived statistic is called for, the results are also cached (using @functools.cached_property).

    * Resource(session["resource"]).assets
    * Resource(session["resource"]).display_name
    * Resource(session["resource"]).get_data()

    Usage
    -----
    >>> from flask import session
    >>> resource = Resource(session["resource"])
    >>> resource.assets
    >>> resource.display_name
    >>> resource.load_sensor_data(Power)
    >>> resource.cached_power_data
    >>> resource.load_sensor_data(Price, sensor_key_attribute="market.name")
    >>> resource.cached_price_data
    """

    # Todo: Our Resource may become an (Aggregated*)Asset with a grouping relationship with other Assets.
    #       Each component asset may have sensors that may have an is_scored_by relationship,
    #       with e.g. a price sensor of a market.
    #       * Asset == AggregatedAsset if it groups assets of only 1 type,
    #         Asset == GeneralizedAsset if it groups assets of multiple types

    assets: List[Asset]
    count: int
    count_all: int
    name: str
    unique_asset_types: List[AssetType]
    unique_asset_type_names: List[str]
    cached_power_data: Dict[
        str, tb.BeliefsDataFrame
    ]  # todo: use standard library caching
    cached_price_data: Dict[str, tb.BeliefsDataFrame]
    asset_name_to_market_name_map: Dict[str, str]

    def __init__(self, name: str):
        """ The resource name is either the name of an asset group or an individual asset. """
        if name is None or name == "":
            raise Exception("Empty resource name passed (%s)" % name)
        self.name = name

        # Query assets for all users to set some public information about the resource
        asset_queries = get_asset_group_queries(
            custom_additional_groups=["renewables", "EVSE", "each Charge Point"],
            all_users=True,
        )
        asset_query = (
            asset_queries[self.name]
            if name in asset_queries
            else Asset.query.filter_by(name=self.name)
        )  # gather assets that are identified by this resource's name

        # List unique asset types and asset type names represented by this resource
        assets = asset_query.all()
        self.unique_asset_types = list(set([a.asset_type for a in assets]))
        self.unique_asset_type_names = list(set([a.asset_type.name for a in assets]))

        # Count all assets in the system that are identified by this resource's name, no matter who is the owner
        self.count_all = len(assets)

        # List all assets that are identified by this resource's name and accessible by the current user
        self.assets = mask_inaccessible_assets(asset_query).all()

        # Count all assets that are identified by this resource's name and accessible by the current user
        self.count = len(self.assets)

        # Construct a convenient mapping to get from an asset name to the market name of the asset's relevant market
        self.asset_name_to_market_name_map = {
            asset.name: asset.market.name if asset.market is not None else None
            for asset in self.assets
        }

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

    def is_eligible_for_comparing_individual_traces(self, max_traces: int = 7) -> bool:
        """
        Decide whether comparing individual traces for assets in this resource
        is a useful feature.
        The number of assets that can be compared is parametrizable with max_traces.
        Plot colors are reused if max_traces > 7, and run out if max_traces > 105.
        """
        return len(self.assets) in range(2, max_traces + 1) and assets_share_location(
            self.assets
        )

    @property
    def hover_label(self) -> Optional[str]:
        """Attempt to get a hover label to show if possible."""
        label = p.join(
            [
                asset_type.hover_label
                for asset_type in self.unique_asset_types
                if asset_type.hover_label is not None
            ]
        )
        return label if label else None

    @property
    def parameterized_name(self) -> str:
        """Get a parameterized name for use in javascript."""
        return parameterize(self.name)

    def load_sensor_data(
        self,
        sensor_types: List[SensorType] = None,
        start: datetime = None,
        end: datetime = None,
        resolution: str = None,
        belief_horizon_window=(None, None),
        belief_time_window=(None, None),
        source_types: Optional[List[str]] = None,
        exclude_source_types: Optional[List[str]] = None,
    ) -> Resource:
        """Load data for one or more assets and cache the results.
        If the time range parameters are None, they will be gotten from the session.
        The horizon window will default to the latest measurement (anything more in the future than the
        end of the time interval.
        To load data for a specific source, pass a source id.

        :returns: self (to allow piping)

        Usage
        -----
        >>> resource = Resource()
        >>> resource.load_sensor_data([Power], start=datetime(2014, 3, 1), end=datetime(2014, 3, 1))
        >>> resource.cached_power_data
        >>> resource.load_sensor_data([Power, Price], start=datetime(2014, 3, 1), end=datetime(2014, 3, 1)).cached_price_data
        """

        # Invalidate old caches
        self.clear_cache()

        # Look up all relevant sensor types for the given resource
        if sensor_types is None:
            # todo: after splitting Assets and Sensors, construct here a list of sensor types
            sensor_types = [Power, Price, Weather]

        # todo: after combining the Power, Price and Weather tables into one TimedBeliefs table,
        #       retrieve data from different sensor types in a single query,
        #       and cache the results grouped by sensor type (cached_price_data, cached_power_data, etc.)
        for sensor_type in sensor_types:
            if sensor_type == Power:
                sensor_key_attribute = "name"
            elif sensor_type == Price:
                sensor_key_attribute = "market.name"
            else:
                raise NotImplementedError("Unsupported sensor type")

            # Determine which sensors we need to query
            names_of_resource_sensors = set(
                coding_utils.rgetattr(asset, sensor_key_attribute)
                for asset in self.assets
            )

            # Query the sensors
            resource_data: Dict[str, tb.BeliefsDataFrame] = sensor_type.collect(
                generic_asset_names=list(names_of_resource_sensors),
                query_window=(start, end),
                belief_horizon_window=belief_horizon_window,
                belief_time_window=belief_time_window,
                source_types=source_types,
                exclude_source_types=exclude_source_types,
                resolution=resolution,
                sum_multiple=False,
            )

            # Cache the data
            setattr(
                self, f"cached_{sensor_type.__name__.lower()}_data", resource_data
            )  # e.g. cached_price_data for sensor type Price
        return self

    @property
    @check_cache("cached_power_data")
    def power_data(self) -> Dict[str, tb.BeliefsDataFrame]:
        return self.cached_power_data

    @property
    @check_cache("cached_price_data")
    def price_data(self) -> Dict[str, tb.BeliefsDataFrame]:
        return self.cached_price_data

    @cached_property
    def demand(self) -> Dict[str, tb.BeliefsDataFrame]:
        """ Returns each asset's demand as positive values. """
        return {k: get_demand_from_bdf(v) for k, v in self.power_data.items()}

    @cached_property
    def supply(self) -> Dict[str, tb.BeliefsDataFrame]:
        """ Returns each asset's supply as positive values. """
        return {k: get_supply_from_bdf(v) for k, v in self.power_data.items()}

    @cached_property
    def aggregate_power_data(self) -> tb.BeliefsDataFrame:
        return aggregate_values(self.power_data)

    @cached_property
    def aggregate_demand(self) -> tb.BeliefsDataFrame:
        """ Returns aggregate demand as positive values. """
        return get_demand_from_bdf(self.aggregate_power_data)

    @cached_property
    def aggregate_supply(self) -> tb.BeliefsDataFrame:
        """ Returns aggregate supply (as positive values). """
        return get_supply_from_bdf(self.aggregate_power_data)

    @cached_property
    def total_demand(self) -> Dict[str, float]:
        """ Returns each asset's total demand as a positive value. """
        return {
            k: v.sum().values[0]
            * time_utils.resolution_to_hour_factor(v.event_resolution)
            for k, v in self.demand.items()
        }

    @cached_property
    def total_supply(self) -> Dict[str, float]:
        """ Returns each asset's total supply as a positive value. """
        return {
            k: v.sum().values[0]
            * time_utils.resolution_to_hour_factor(v.event_resolution)
            for k, v in self.supply.items()
        }

    @cached_property
    def total_aggregate_demand(self) -> float:
        """ Returns total aggregate demand as a positive value. """
        return self.aggregate_demand.sum().values[
            0
        ] * time_utils.resolution_to_hour_factor(self.aggregate_demand.event_resolution)

    @cached_property
    def total_aggregate_supply(self) -> float:
        """ Returns total aggregate supply as a positive value. """
        return self.aggregate_supply.sum().values[
            0
        ] * time_utils.resolution_to_hour_factor(self.aggregate_supply.event_resolution)

    @cached_property
    def revenue(self) -> Dict[str, float]:
        """ Returns each asset's total revenue from supply. """
        revenue_dict = {}
        for k, v in self.supply.items():
            market_name = self.asset_name_to_market_name_map[k]
            if market_name is not None:
                revenue_dict[k] = (
                    simplify_index(v) * simplify_index(self.price_data[market_name])
                ).sum().values[0] * time_utils.resolution_to_hour_factor(
                    v.event_resolution
                )
            else:
                revenue_dict[k] = None
        return revenue_dict

    @cached_property
    def aggregate_revenue(self) -> float:
        """ Returns total aggregate revenue from supply. """
        return sum(self.revenue.values())

    @cached_property
    def cost(self) -> Dict[str, float]:
        """ Returns each asset's total cost from demand. """
        cost_dict = {}
        for k, v in self.demand.items():
            market_name = self.asset_name_to_market_name_map[k]
            if market_name is not None:
                cost_dict[k] = (
                    simplify_index(v) * simplify_index(self.price_data[market_name])
                ).sum().values[0] * time_utils.resolution_to_hour_factor(
                    v.event_resolution
                )
            else:
                cost_dict[k] = None
        return cost_dict

    @cached_property
    def aggregate_cost(self) -> float:
        """ Returns total aggregate cost from demand. """
        return sum(self.cost.values())

    @cached_property
    def aggregate_profit_or_loss(self) -> float:
        """ Returns total aggregate profit (loss is negative). """
        return self.aggregate_revenue - self.aggregate_cost

    def clear_cache(self):
        self.cached_power_data = {}
        self.cached_price_data = {}
        for prop in coding_utils.methods_with_decorator(Resource, cached_property):
            if prop.__name__ in self.__dict__:
                del self.__dict__[prop.__name__]

    def __str__(self):
        return self.display_name


def get_demand_from_bdf(
    bdf: Union[pd.DataFrame, tb.BeliefsDataFrame]
) -> Union[pd.DataFrame, tb.BeliefsDataFrame]:
    """ Positive values become 0 and negative values become positive values. """
    return bdf.clip(upper=0).abs()


def get_supply_from_bdf(
    bdf: Union[pd.DataFrame, tb.BeliefsDataFrame]
) -> Union[pd.DataFrame, tb.BeliefsDataFrame]:
    """ Negative values become 0. """
    return bdf.clip(lower=0)


def get_sensor_types(resource: Resource) -> List[WeatherSensorType]:
    """Return a list of WeatherSensorType objects applicable to the given resource."""
    sensor_type_names = []
    for asset_type in resource.unique_asset_types:
        sensor_type_names.extend(asset_type.weather_correlations)
    unique_sensor_type_names = list(set(sensor_type_names))

    sensor_types = []
    for name in unique_sensor_type_names:
        sensor_type = WeatherSensorType.query.filter(
            WeatherSensorType.name == name
        ).one_or_none()
        if sensor_type is not None:
            sensor_types.append(sensor_type)

    return sensor_types


def find_closest_weather_sensor(
    sensor_type: str, n: int = 1, **kwargs
) -> Union[WeatherSensor, List[WeatherSensor], None]:
    """Returns the closest n weather sensors of a given type (as a list if n > 1).
    Parses latitude and longitude values stated in kwargs.

    Can be called with an object that has latitude and longitude properties, for example:

        sensor = find_closest_weather_sensor("wind_speed", object=asset)

    Can also be called with latitude and longitude parameters, for example:

        sensor = find_closest_weather_sensor("temperature", latitude=32, longitude=54)
        sensor = find_closest_weather_sensor("temperature", lat=32, lng=54)

    """

    latitude, longitude = parse_lat_lng(kwargs)
    sensors = WeatherSensor.query.filter(
        WeatherSensor.weather_sensor_type_name == sensor_type
    ).order_by(WeatherSensor.great_circle_distance(lat=latitude, lng=longitude).asc())
    if n == 1:
        return sensors.first()
    else:
        return sensors.limit(n).all()


def group_assets_by_location(asset_list: List[Asset]) -> List[List[Asset]]:
    groups = []

    def key_function(x):
        return x.location

    sorted_asset_list = sorted(asset_list, key=key_function)
    for _k, g in groupby(sorted_asset_list, key=key_function):
        groups.append(list(g))
    return groups
