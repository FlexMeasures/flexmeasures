from typing import Union, Type

from flexmeasures.data.models.assets import AssetType, Asset, Power
from flexmeasures.data.models.markets import MarketType, Market, Price
from flexmeasures.data.models.weather import WeatherSensorType, WeatherSensor, Weather


def determine_asset_type_by_asset(
    generic_asset: Union[Asset, Market, WeatherSensor]
) -> Union[AssetType, MarketType, WeatherSensorType]:
    if isinstance(generic_asset, Asset):
        return generic_asset.asset_type
    elif isinstance(generic_asset, Market):
        return generic_asset.market_type
    elif isinstance(generic_asset, WeatherSensor):
        return generic_asset.sensor_type
    else:
        raise TypeError("Unknown generic asset type.")


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
