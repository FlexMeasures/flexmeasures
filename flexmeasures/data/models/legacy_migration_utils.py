"""
This module is part of our data model migration (see https://github.com/SeitaBV/flexmeasures/projects/9).
It will become obsolete when Assets, Markets and WeatherSensors can no longer be initialized.
"""

from __future__ import annotations

from datetime import datetime

from flexmeasures.data import db
from flexmeasures.utils.unit_utils import is_energy_unit, ur, is_power_unit


class NonDowngradableValueError(ValueError):
    pass


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
        a: (
            getattr(old_sensor, a)
            if not isinstance(getattr(old_sensor, a), datetime)
            else getattr(old_sensor, a).isoformat()
        )
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


def upgrade_value(
    old_field_name: str, old_value: int | float | dict | bool, sensor=None, asset=None
) -> str | int | float | dict | bool:
    """Depending on the old field name, some values still need to be turned into string quantities."""

    # check if value is an int, bool, float or dict
    if not isinstance(old_value, (int, float, dict, bool, str)):
        if sensor:
            raise Exception(
                f"Invalid value for '{old_field_name}' in sensor {sensor.id}: {old_value}"
            )
        elif asset:
            raise Exception(
                f"Invalid value for '{old_field_name}' in asset {asset.id}: {old_value}"
            )
    if old_field_name[-6:] == "in_mwh" and isinstance(old_value, (float, int)):
        # convert from float (in MWh) to string (in kWh)
        value_in_kwh = old_value * 1000
        return f"{value_in_kwh} kWh"
    elif old_field_name[-5:] == "in_mw" and isinstance(old_value, (float, int)):
        # convert from float (in MW) to string (in kW)
        value_in_kw = old_value * 1000
        return f"{value_in_kw} kW"
    elif old_field_name in ("soc-gain", "soc-usage") and isinstance(old_value, str):
        return [old_value]
    else:
        # move as is
        return old_value


def downgrade_value(old_field_name: str, new_value) -> float | str | dict:
    """Depending on the old field name, some values still need to be turned back into floats."""
    if isinstance(new_value, str):
        # Convert the value back to the original format
        if old_field_name[-6:] == "in_mwh" and is_energy_unit(new_value):
            value_in_mwh = round(ur.Quantity(new_value).to("MWh").magnitude, 6)
            return value_in_mwh
        elif old_field_name[-5:] == "in_mw" and is_power_unit(new_value):
            value_in_mw = round(ur.Quantity(new_value).to("MW").magnitude, 6)
            return value_in_mw
        else:
            # Return string quantity
            return new_value
    elif isinstance(new_value, dict):
        # Return sensor reference
        return new_value
    else:
        raise NonDowngradableValueError()
