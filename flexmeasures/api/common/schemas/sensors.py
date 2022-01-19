from flask import abort
from marshmallow import fields

from flexmeasures.api import FMValidationError
from flexmeasures.api.common.utils.api_utils import (
    get_sensor_by_generic_asset_type_and_location,
)
from flexmeasures.utils.entity_address_utils import (
    parse_entity_address,
    EntityAddressException,
)
from flexmeasures.data.models.time_series import Sensor


class EntityAddressValidationError(FMValidationError):
    status = "INVALID_DOMAIN"  # USEF error status


class SensorIdField(fields.Integer):
    """
    Field that represents a sensor ID. It de-serializes from the sensor id to a sensor instance.
    """

    def _deserialize(self, sensor_id: int, attr, obj, **kwargs) -> Sensor:
        sensor: Sensor = Sensor.query.filter_by(id=int(sensor_id)).one_or_none()
        if sensor is None:
            raise abort(404, f"Sensor {sensor_id} not found")
        return sensor

    def _serialize(self, sensor: Sensor, attr, data, **kwargs) -> int:
        return sensor.id


class SensorField(fields.Str):
    """Field that de-serializes to a Sensor,
    and serializes a Sensor, Asset, Market or WeatherSensor into an entity address (string)."""

    # todo: when Actuators also get an entity address, refactor this class to EntityField,
    #       where an Entity represents anything with an entity address: we currently foresee Sensors and Actuators

    def __init__(
        self,
        entity_type: str,
        fm_scheme: str,
        *args,
        **kwargs,
    ):
        """
        :param entity_type: "sensor", "connection", "market" or "weather_sensor"
        :param fm_scheme:   "fm0" or "fm1"
        """
        self.entity_type = entity_type
        self.fm_scheme = fm_scheme
        super().__init__(*args, **kwargs)

    def _deserialize(self, value, attr, obj, **kwargs) -> Sensor:
        """De-serialize to a Sensor."""
        try:
            ea = parse_entity_address(value, self.entity_type, self.fm_scheme)
            if self.fm_scheme == "fm0":
                if self.entity_type == "connection":
                    sensor = Sensor.query.filter(
                        Sensor.id == ea["asset_id"]
                    ).one_or_none()
                elif self.entity_type == "market":
                    sensor = Sensor.query.filter(
                        Sensor.name == ea["market_name"]
                    ).one_or_none()
                elif self.entity_type == "weather_sensor":
                    sensor = get_sensor_by_generic_asset_type_and_location(
                        ea["weather_sensor_type_name"], ea["latitude"], ea["longitude"]
                    )
                else:
                    return NotImplemented
            else:
                sensor = Sensor.query.filter(Sensor.id == ea["sensor_id"]).one_or_none()
            if sensor is not None:
                return sensor
            else:
                raise EntityAddressValidationError(
                    f"{self.entity_type} with entity address {value} doesn't exist."
                )
        except EntityAddressException as eae:
            raise EntityAddressValidationError(str(eae))

    def _serialize(self, value: Sensor, attr, data, **kwargs):
        """Serialize to an entity address."""
        if self.fm_scheme == "fm0":
            return value.entity_address_fm0
        else:
            return value.entity_address
