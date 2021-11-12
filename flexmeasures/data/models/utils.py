from typing import Union, Type

from flexmeasures.data.models.assets import Asset, Power
from flexmeasures.data.models.markets import Market, Price
from flexmeasures.data.models.weather import WeatherSensor, Weather


def determine_old_time_series_class_by_old_sensor(
    old_sensor: Union[Asset, Market, WeatherSensor]
) -> Type[Union[Power, Price, Weather]]:
    if isinstance(old_sensor, Asset):
        return Power
    elif isinstance(old_sensor, Market):
        return Price
    elif isinstance(old_sensor, WeatherSensor):
        return Weather
    else:
        raise TypeError("Unknown old sensor type.")
