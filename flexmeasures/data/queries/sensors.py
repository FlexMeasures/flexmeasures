from __future__ import annotations

from sqlalchemy.sql import Select, select

from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.queries.utils import potentially_limit_assets_query_to_account


def query_sensor_by_name_and_generic_asset_type_name(
    sensor_name: str | None = None,
    generic_asset_type_names: list[str] | None = None,
    account_id: int | None = None,
) -> Select:
    """Match a sensor by its own name and that of its generic asset type.

    :param sensor_name: should match (if None, no match is needed)
    :param generic_asset_type_names: should match at least one of these (if None, no match is needed)
    :param account_id: Pass in an account ID if you want to query an account other than your own. This only works for admins. Public assets are always queried.
    """
    from flexmeasures.data.models.time_series import Sensor

    query = select(Sensor)
    if sensor_name is not None:
        query = query.filter(Sensor.name == sensor_name)
    if generic_asset_type_names is not None:
        query = (
            query.join(GenericAsset)
            .join(GenericAssetType)
            .filter(GenericAssetType.name.in_(generic_asset_type_names))
            .filter(GenericAsset.generic_asset_type_id == GenericAssetType.id)
            .filter(Sensor.generic_asset_id == GenericAsset.id)
        )
    query = potentially_limit_assets_query_to_account(query, account_id)
    return query


def query_sensors_by_proximity(
    latitude: float,
    longitude: float,
    generic_asset_type_name: str | None,
    sensor_name: str | None,
    account_id: int | None = None,
) -> Select:
    """Order them by proximity of their asset's location to the target."""
    from flexmeasures.data.models.time_series import Sensor

    closest_sensor_query = (
        select(Sensor)
        .join(GenericAsset, Sensor.generic_asset_id == GenericAsset.id)
        .filter(Sensor.generic_asset_id == GenericAsset.id)
    )
    if generic_asset_type_name:
        closest_sensor_query = closest_sensor_query.join(GenericAssetType)
        closest_sensor_query = closest_sensor_query.filter(
            Sensor.generic_asset_id == GenericAsset.id,
            GenericAsset.generic_asset_type_id == GenericAssetType.id,
            GenericAssetType.name == generic_asset_type_name,
        )
    if sensor_name is not None:
        closest_sensor_query = closest_sensor_query.filter(Sensor.name == sensor_name)
    closest_sensor_query = closest_sensor_query.order_by(
        GenericAsset.great_circle_distance(lat=latitude, lng=longitude).asc()
    )
    closest_sensor_query = potentially_limit_assets_query_to_account(
        closest_sensor_query, account_id
    )
    return closest_sensor_query
