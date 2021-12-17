from typing import List, Optional

from sqlalchemy.orm import Query

from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.models.time_series import Sensor


def query_sensor_by_name_and_generic_asset_type_name(
    sensor_name: Optional[str] = None,
    generic_asset_type_names: Optional[List[str]] = None,
) -> Query:
    """Match a sensor by its own name and that of its generic asset type.

    :param sensor_name: should match (if None, no match is needed)
    :param generic_asset_type_names: should match at least one of these (if None, no match is needed)
    """
    query = Sensor.query
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
    return query


def query_sensors_by_proximity(
    generic_asset_type_name: str, latitude: float, longitude: float
) -> Query:
    """Match sensors by the name of their generic asset type, and order them by proximity."""
    closest_sensor_query = (
        Sensor.query.join(GenericAsset, GenericAssetType)
        .filter(
            Sensor.generic_asset_id == GenericAsset.id,
            GenericAsset.generic_asset_type_id == GenericAssetType.id,
            GenericAssetType.name == generic_asset_type_name,
        )
        .order_by(GenericAsset.great_circle_distance(lat=latitude, lng=longitude).asc())
    )
    return closest_sensor_query
