"""
This module is part of our data model migration (see https://github.com/SeitaBV/flexmeasures/projects/9).
It will become obsolete when Assets, Markets and WeatherSensors can no longer be initialized.
"""
from __future__ import annotations

from datetime import datetime

from flexmeasures.data import db


def copy_old_sensor_attributes(
    old_sensor,
    old_sensor_type_attributes: list[str],
    old_sensor_attributes: list[str],
    old_sensor_type: "AssetType | MarketType | WeatherSensorType" = None,  # noqa F821
) -> dict:
    """
    :param old_sensor: an Asset, Market or WeatherSensor instance
    :param old_sensor_type_attributes: names of attributes of the old sensor's type that should be copied
    :param old_sensor_attributes: names of attributes of the old sensor that should be copied
    :param old_sensor_type: the old sensor's type
    :returns: dictionary containing an "attributes" dictionary with attribute names and values
    """
    new_model_attributes_from_old_sensor_type = {
        a: getattr(old_sensor_type, a) for a in old_sensor_type_attributes
    }
    new_model_attributes_from_old_sensor = {
        a: getattr(old_sensor, a)
        if not isinstance(getattr(old_sensor, a), datetime)
        else getattr(old_sensor, a).isoformat()
        for a in old_sensor_attributes
    }
    return dict(
        attributes={
            **new_model_attributes_from_old_sensor_type,
            **new_model_attributes_from_old_sensor,
        }
    )


def get_old_model_type(
    kwargs: dict,
    old_sensor_type_class: "Type[AssetType | MarketType | WeatherSensorType]",  # noqa F821
    old_sensor_type_name_key: str,
    old_sensor_type_key: str,
) -> "AssetType | MarketType | WeatherSensorType":  # noqa F821
    """
    :param kwargs: keyword arguments used to initialize a new Asset, Market or WeatherSensor
    :param old_sensor_type_class: AssetType, MarketType, or WeatherSensorType
    :param old_sensor_type_name_key: "asset_type_name", "market_type_name", or "weather_sensor_type_name"
    :param old_sensor_type_key: "asset_type", "market_type", or "sensor_type" (instead of "weather_sensor_type"),
                                i.e. the name of the class attribute for the db.relationship to the type's class
    :returns: the old sensor's type
    """
    if old_sensor_type_name_key in kwargs:
        old_sensor_type = db.session.get(
            old_sensor_type_class, kwargs[old_sensor_type_name_key]
        )
    else:
        old_sensor_type = kwargs[old_sensor_type_key]
    return old_sensor_type
