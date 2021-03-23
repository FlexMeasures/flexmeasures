from typing import Union

from marshmallow import fields

from flexmeasures.api import FMValidationError
from flexmeasures.api.common.utils.api_utils import get_weather_sensor_by
from flexmeasures.utils.entity_address_utils import (
    parse_entity_address,
    EntityAddressException,
)
from flexmeasures.data.models.assets import Asset
from flexmeasures.data.models.markets import Market
from flexmeasures.data.models.weather import WeatherSensor
from flexmeasures.data.models.time_series import Sensor


class EntityAddressValidationError(FMValidationError):
    status = "INVALID_DOMAIN"  # USEF error status


class SensorField(fields.Str):
    """Field that deserializes to a Sensor, Asset, Market or WeatherSensor
    and serializes back to an entity address (string)."""

    def __init__(
        self,
        entity_type: str,
        *args,
        **kwargs,
    ):
        """
        :param entity_type: "sensor", "connection", "market" or "weather_sensor"
        """
        self.entity_type = entity_type
        super().__init__(*args, **kwargs)

    def _deserialize(
        self, value, attr, obj, **kwargs
    ) -> Union[Sensor, Asset, Market, WeatherSensor]:
        """Deserialize to a Sensor, Asset, Market or WeatherSensor."""
        try:
            ea = parse_entity_address(value, self.entity_type)
            if self.entity_type == "sensor":
                sensor = Sensor.query.filter(Sensor.id == ea["sensor_id"]).one_or_none()
                if sensor is not None:
                    return sensor
                else:
                    raise EntityAddressValidationError(
                        f"Sensor with entity address {value} doesn't exist."
                    )
            elif self.entity_type == "connection":
                asset = Asset.query.filter(Asset.id == ea["asset_id"]).one_or_none()
                if asset is not None:
                    return asset
                else:
                    raise EntityAddressValidationError(
                        f"Asset with entity address {value} doesn't exist."
                    )
            elif self.entity_type == "market":
                market = Market.query.filter(
                    Market.name == ea["market_name"]
                ).one_or_none()
                if market is not None:
                    return market
                else:
                    raise EntityAddressValidationError(
                        f"Market with entity address {value} doesn't exist."
                    )
            elif self.entity_type == "weather_sensor":
                weather_sensor = get_weather_sensor_by(
                    ea["weather_sensor_type_name"], ea["latitude"], ea["longitude"]
                )
                if weather_sensor is not None and isinstance(
                    weather_sensor, WeatherSensor
                ):
                    return weather_sensor
                else:
                    raise EntityAddressValidationError(
                        f"Weather sensor with entity address {value} doesn't exist."
                    )
        except EntityAddressException as eae:
            raise EntityAddressValidationError(str(eae))

    def _serialize(
        self, value: Union[Sensor, Asset, Market, WeatherSensor], attr, data, **kwargs
    ):
        """Serialize to an entity address."""
        return value.entity_address
