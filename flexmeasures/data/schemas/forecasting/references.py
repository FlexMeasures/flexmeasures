"""Sensor references a forecaster's config can hold, including one for the sensor being forecast."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.schemas.sensors import (
    SensorIdOrReferenceField,
    SensorReference,
)

#: What a forecaster's config writes where it means the sensor being forecast,
#: which only the forecast parameters name.
AUTO_SENSOR = "auto"


@dataclass
class AutoSensorReference:
    """A reference to the sensor being forecast, before that sensor is known.

    A forecaster's config is written once and used for whichever sensor a forecast names,
    so a config that wants to say something about that sensor writes ``"auto"`` in place of its ID.
    The reference holds the qualifiers it was given, and turns into an ordinary sensor reference once the target is known.
    """

    qualifiers: dict[str, Any] = field(default_factory=dict)

    def resolve(self, target_sensor: Sensor) -> Sensor | SensorReference:
        """Return what this reference means for the sensor being forecast.

        :param target_sensor: The sensor the forecast is made for.
        :returns:             A plain :class:`~flexmeasures.data.models.time_series.Sensor` when no qualifiers were given, and a :class:`SensorReference` otherwise.
        """
        return SensorIdOrReferenceField().deserialize(
            {"sensor": target_sensor.id, **self.qualifiers}
        )


class ForecastInputField(SensorIdOrReferenceField):
    """A sensor a forecaster reads from: a sensor ID, a sensor reference, or ``"auto"``.

    ``"auto"`` names the sensor being forecast, which a config cannot name by ID without being tied to one target.
    It may be written on its own, or as the ``sensor`` of a reference that qualifies it, as in ``{"sensor": "auto", "lower": "0 kW"}``.
    """

    def __init__(self, *args, **kwargs):
        metadata = dict(kwargs.pop("metadata", {}))
        metadata.setdefault(
            "oneOf",
            [
                {"type": "integer"},
                {"type": "string", "enum": [AUTO_SENSOR]},
                {"$ref": "#/components/schemas/SensorReference"},
            ],
        )
        kwargs["metadata"] = metadata
        super().__init__(*args, **kwargs)

    def _deserialize(
        self, value: Any, attr, data, **kwargs
    ) -> Sensor | SensorReference | AutoSensorReference:
        if value == AUTO_SENSOR:
            return AutoSensorReference()
        if isinstance(value, dict) and value.get("sensor") == AUTO_SENSOR:
            return AutoSensorReference(
                {key: item for key, item in value.items() if key != "sensor"}
            )
        return super()._deserialize(value, attr, data, **kwargs)

    def _serialize(
        self, value: Sensor | SensorReference | AutoSensorReference, attr, obj, **kwargs
    ) -> Any:
        """Serialize a sensor, a reference, or the sentinel naming the sensor being forecast."""
        if isinstance(value, AutoSensorReference):
            if not value.qualifiers:
                return AUTO_SENSOR
            return {"sensor": AUTO_SENSOR, **value.qualifiers}
        return super()._serialize(value, attr, obj, **kwargs)
