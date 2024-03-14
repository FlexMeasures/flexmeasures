from flask import abort
from marshmallow import fields
from sqlalchemy import select

from flexmeasures.data import db
from flexmeasures.api import FMValidationError
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
        sensor: Sensor = db.session.execute(
            select(Sensor).filter_by(id=int(sensor_id))
        ).scalar_one_or_none()
        if sensor is None:
            raise abort(404, f"Sensor {sensor_id} not found")
        return sensor

    def _serialize(self, sensor: Sensor, attr, data, **kwargs) -> int:
        return sensor.id


class SensorField(fields.Str):
    """Field that de-serializes to a Sensor,
    and serializes a Sensor into an entity address (string).
    """

    # todo: when Actuators also get an entity address, refactor this class to EntityField,
    #       where an Entity represents anything with an entity address: we currently foresee Sensors and Actuators

    def __init__(
        self,
        entity_type: str = "sensor",
        fm_scheme: str = "fm1",
        *args,
        **kwargs,
    ):
        """
        :param entity_type: "sensor" (in the future, possibly also another type of resource that is assigned an entity address)
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
                raise EntityAddressException("The fm0 scheme is no longer supported.")
            else:
                sensor = db.session.execute(
                    select(Sensor).filter_by(id=ea["sensor_id"])
                ).scalar_one_or_none()
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
