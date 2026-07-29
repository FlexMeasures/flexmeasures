"""Schema for referencing a group of devices whose aggregate power is constrained.

Kept in its own module (rather than in ``storage.py``) so that both the storage
flex-model schemas and the flex-context's inflexible-device schema can reference a
group, without ``schemas/scheduling/__init__.py`` having to import ``storage.py``
(which would create an import cycle).
"""

from __future__ import annotations

from marshmallow import validates_schema, ValidationError

from flexmeasures import Sensor
from flexmeasures.data.schemas.generic_assets import GenericAssetIdField
from flexmeasures.data.schemas.sensors import (
    SensorIdField,
    SensorReference,
    SharedSensorReferenceSchema,
)
from flexmeasures.utils.unit_utils import is_power_unit


def validate_group_sensor_is_power_sensor(group: dict):
    """Check that the sensor referenced by the `group` field measures power."""
    sensor = group.get("sensor")
    if isinstance(sensor, (Sensor, SensorReference)) and not is_power_unit(sensor.unit):
        raise ValidationError(
            "The `group` field must reference a sensor with a power unit.",
            field_name="group",
        )


class GroupReferenceSchema(SharedSensorReferenceSchema):
    """Reference to a group of devices whose aggregate power is constrained.

    Accepts exactly one of:
      - ``{"sensor": <id>}``: the group's aggregate power is stored on this power sensor
        (the sensor must itself carry a flex-model entry defining the group's
        constraints).
      - ``{"asset": <id>}``: the group is identified by the flex-model entry on this
        asset (typically a sub-EMS/asset in the tree). Such a group entry defines no
        power sensor of its own; instead it may define ``consumption`` and/or
        ``production`` output sensors on which the group's aggregate power gets saved,
        following the usual output-sensor conventions.

    Inherits from ``SharedSensorReferenceSchema`` (not ``SensorReferenceSchema``) so it
    accepts only ``sensor``/``asset`` -- a group is a device-group identifier, not a
    belief-query reference, so the ``source-*`` filter fields do not apply.
    """

    class Meta:
        description = (
            "Reference to a group of devices whose aggregate power is constrained."
        )

    sensor = SensorIdField(required=False)
    asset = GenericAssetIdField(required=False)

    @validates_schema
    def validate_exactly_one_reference(self, data: dict, **kwargs):
        has_sensor = "sensor" in data
        has_asset = "asset" in data
        if has_sensor == has_asset:  # both or neither
            raise ValidationError(
                "The `group` field must reference exactly one of 'sensor' or 'asset'."
            )
