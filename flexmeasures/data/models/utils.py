from typing import Union, Type

from flexmeasures.data.models.assets import Asset, Power
from flexmeasures.data.models.markets import Market, Price
from flexmeasures.data.models.weather import WeatherSensor, Weather


def determine_asset_value_class_by_asset(
    generic_asset: Union[Asset, Market, WeatherSensor]
) -> Type[Union[Power, Price, Weather]]:
    if isinstance(generic_asset, Asset):
        return Power
    elif isinstance(generic_asset, Market):
        return Price
    elif isinstance(generic_asset, WeatherSensor):
        return Weather
    else:
        raise TypeError("Unknown generic asset type.")
