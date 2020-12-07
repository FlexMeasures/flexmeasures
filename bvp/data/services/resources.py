"""
Generic services for accessing asset data.
"""

from typing import List, Dict, Union, Optional
from datetime import datetime
from bvp.utils.bvp_inflection import parameterize, pluralize
from itertools import groupby

from flask_security.core import current_user
import inflect
from sqlalchemy.orm.query import Query
import timely_beliefs as tb

from bvp.data.models.assets import AssetType, Asset, Power
from bvp.data.models.markets import Market
from bvp.data.models.weather import WeatherSensorType, WeatherSensor
from bvp.utils.geo_utils import parse_lat_lng


p = inflect.engine()


class InvalidBVPAsset(Exception):
    pass


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
    cps = group_assets_by_location(all_evse_assets)
    for cp in cps:
        charge_point_name = cp[0].display_name.split(" -")[0] + " (Charge Point)"
        asset_queries[charge_point_name] = Asset.query.filter(
            Asset.name.in_([evse.name for evse in cp])
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


class Resource:
    """
    This class represents a resource and helps to map names to assets.
    A "resource" is an umbrella term:

    * It can be one asset / market.
    * It can be a group of assets / markets. (see get_asset_group_queries)

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

    assets: List[Asset]
    count: int
    count_all: int
    name: str
    unique_asset_types: List[AssetType]
    unique_asset_type_names: List[str]

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

    def get_data(
        self,
        start: datetime = None,
        end: datetime = None,
        resolution: str = None,
        horizon_window=(None, None),
        rolling: bool = True,
        user_source_id: int = None,
        source_types: Optional[List[str]] = None,
        sum_multiple: bool = True,
    ) -> Union[tb.BeliefsDataFrame, Dict[str, tb.BeliefsDataFrame]]:
        """Get data for one or more assets. TODO: market data?
        If the time range parameters are None, they will be gotten from the session.
        The horizon window will default to the latest measurement (anything more in the future than the
        end of the time interval.
        To get data for a specific source, pass a source id.
        TODO: can this be retired in favor of data.services.time_series?
        """

        data = Power.collect(
            generic_asset_names=[asset.name for asset in self.assets],
            query_window=(start, end),
            horizon_window=horizon_window,
            rolling=rolling,
            preferred_user_source_ids=user_source_id,
            source_types=source_types,
            resolution=resolution,
            sum_multiple=sum_multiple,
        )
        return data

    def __str__(self):
        return self.display_name


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
    for _k, g in groupby(asset_list, lambda x: x.location):
        groups.append(list(g))
    return groups
