from datetime import datetime
from typing import List

from flexmeasures.data import db


def copy_old_sensor_attributes(
    old_sensor,
    kwargs,
    old_sensor_type_class: "Type[Union[AssetType, MarketType, WeatherSensorType]]",  # noqa F821
    old_sensor_type_name_key: str,
    old_sensor_type_key: str,
    old_sensor_type_attributes: List[str],
    old_sensor_attributes: List[str],
) -> dict:
    generic_asset_kwargs = kwargs.copy()
    if old_sensor_type_name_key in generic_asset_kwargs:
        old_sensor_type = db.session.query(old_sensor_type_class).get(
            generic_asset_kwargs[old_sensor_type_name_key]
        )
    else:
        old_sensor_type = generic_asset_kwargs[old_sensor_type_key]
    generic_asset_attributes_from_old_sensor_type = {
        a: getattr(old_sensor_type, a) for a in old_sensor_type_attributes
    }
    generic_asset_attributes_from_old_sensor = {
        a: getattr(old_sensor, a)
        if not isinstance(getattr(old_sensor, a), datetime)
        else getattr(old_sensor, a).isoformat()
        for a in old_sensor_attributes
    }
    generic_asset_kwargs = {
        **generic_asset_kwargs,
        **{
            "attributes": {
                **generic_asset_attributes_from_old_sensor_type,
                **generic_asset_attributes_from_old_sensor,
            },
        },
    }
    return generic_asset_kwargs
