from datetime import datetime
from typing import List

from flexmeasures.data import db


def copy_old_sensor_attributes(
    old_sensor,
    new_model_kwargs,
    old_sensor_type_class: "Type[Union[AssetType, MarketType, WeatherSensorType]]",  # noqa F821
    old_sensor_type_name_key: str,
    old_sensor_type_key: str,
    old_sensor_type_attributes: List[str],
    old_sensor_attributes: List[str],
    old_sensor_type: "Union[AssetType, MarketType, WeatherSensorType]" = None,  # noqa F821
) -> dict:
    if old_sensor_type is None and old_sensor_type_name_key in new_model_kwargs:
        old_sensor_type = db.session.query(old_sensor_type_class).get(
            new_model_kwargs[old_sensor_type_name_key]
        )
    elif old_sensor_type is None:
        old_sensor_type = new_model_kwargs[old_sensor_type_key]
    new_model_attributes_from_old_sensor_type = {
        a: getattr(old_sensor_type, a) for a in old_sensor_type_attributes
    }
    new_model_attributes_from_old_sensor = {
        a: getattr(old_sensor, a)
        if not isinstance(getattr(old_sensor, a), datetime)
        else getattr(old_sensor, a).isoformat()
        for a in old_sensor_attributes
    }
    new_model_kwargs = {
        **new_model_kwargs,
        **{
            "attributes": {
                **new_model_attributes_from_old_sensor_type,
                **new_model_attributes_from_old_sensor,
            },
        },
    }
    return new_model_kwargs
