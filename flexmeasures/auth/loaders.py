from __future__ import annotations

from typing import Any

from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.schemas.sensors import SensorIdField


def flex_model_loader(flex_model: dict | list | None) -> dict[str, list[Sensor]]:
    """Extract sensor references from a flex-model for permission checking."""
    return sensor_references_loader(flex_model, ("json", "flex-model"))


def flex_context_loader(flex_context: dict | list | None) -> dict[str, list[Sensor]]:
    """Extract sensor references from a flex-context for permission checking."""
    return sensor_references_loader(flex_context, ("json", "flex-context"))


def sensor_references_loader(
    data: Any, label_path: tuple[str | int, ...]
) -> dict[str, list[Sensor]]:
    """Extract sensor references from nested request data, grouped by field label."""
    sensor_refs: dict[str, list[Sensor]] = {}
    _collect_sensor_references(data, label_path, sensor_refs)
    return sensor_refs


def _collect_sensor_references(
    data: Any,
    label_path: tuple[str | int, ...],
    sensor_refs: dict[str, list[Sensor]],
) -> None:
    if data is None:
        return

    if isinstance(data, dict):
        for field, value in data.items():
            field_path = (*label_path, field)
            if _is_sensor_reference_field(field):
                _add_sensor_reference(sensor_refs, field_path, value)
            elif _is_sensor_reference_list_field(field):
                for sensor in _listify(value):
                    _add_sensor_reference(sensor_refs, field_path, sensor)
            else:
                _collect_sensor_references(value, field_path, sensor_refs)
        return

    if isinstance(data, list):
        for index, value in enumerate(data):
            _collect_sensor_references(value, (*label_path, index), sensor_refs)


def _add_sensor_reference(
    sensor_refs: dict[str, list[Sensor]],
    label_path: tuple[str | int, ...],
    sensor: Sensor | int,
) -> None:
    label = _nested_label(label_path)
    sensor_refs.setdefault(label, []).append(_load_sensor(sensor))


def _load_sensor(sensor: Sensor | int) -> Sensor:
    if isinstance(sensor, Sensor):
        return sensor
    return SensorIdField().deserialize(sensor)


def _is_sensor_reference_field(field: Any) -> bool:
    normalized_field = str(field).replace("_", "-")
    return normalized_field == "sensor" or normalized_field.endswith("-sensor")


def _is_sensor_reference_list_field(field: Any) -> bool:
    normalized_field = str(field).replace("_", "-")
    return normalized_field == "sensors" or normalized_field.endswith("-sensors")


def _listify(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    return [value]


def _nested_label(label_path: tuple[str | int, ...]) -> str:
    label: str | int | dict[str | int, Any] = label_path[-1]
    for field in reversed(label_path[:-1]):
        label = {field: label}
    return str(label)
