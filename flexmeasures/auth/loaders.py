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


# Fields naming a sensor that a scheduler records its results on, rather than reads from, in both spellings
# (flex-config keys use hyphens; deserialized data uses underscores).
# This one list is used wherever output sensors are told apart from inputs: stored flex-contexts and flex-models
# (FLEX_CONFIG_OUTPUT_FIELDS), schedule triggers (SCHEDULE_OUTPUT_FIELDS) and scheduling automations
# (flexmeasures.data.services.automations), so that a new output field is guarded the same way everywhere.
# Extend it whenever a flex-model or flex-context field starts naming somewhere results are recorded.
OUTPUT_SENSOR_FIELDS = frozenset(
    {
        *("consumption", "production"),
        *("aggregate-consumption", "aggregate_consumption"),
        *("aggregate-production", "aggregate_production"),
        *("aggregate-power", "aggregate_power"),
        *("state-of-charge", "state_of_charge"),
        "group",
    }
)

# Flex-config fields whose sensor the scheduler records its results on (see OUTPUT_SENSOR_FIELDS).
FLEX_CONFIG_OUTPUT_FIELDS = OUTPUT_SENSOR_FIELDS


def flex_config_sensor_references(
    flex_config: dict | list | None,
) -> tuple[list[Sensor], list[Sensor]]:
    """Return all sensors a flex-context or flex-model refers to, and those among them that the scheduler records results on.

    A sensor referenced anywhere under one of the FLEX_CONFIG_OUTPUT_FIELDS counts as an output.
    """
    references = flex_config_sensor_reference_paths(flex_config)
    all_sensors = [sensor for _, sensor, _ in references]
    output_sensors = [sensor for _, sensor, is_output in references if is_output]
    return all_sensors, output_sensors


def flex_config_sensor_reference_paths(
    flex_config: dict | list | None,
) -> list[tuple[tuple[str, ...], Sensor, bool]]:
    """Return each sensor reference in a flex-context or flex-model, with its field path and whether it is an output.

    The field path holds the field names leading to the reference (list positions are left out,
    and underscores are written as hyphens), such as ``("consumption-price", "sensor")``.
    """
    references: list[tuple[tuple[str, ...], Sensor, bool]] = []
    _collect_flex_config_sensors(flex_config, (), False, references)
    return references


def _collect_flex_config_sensors(
    data: Any,
    path: tuple[str, ...],
    is_output: bool,
    references: list[tuple[tuple[str, ...], Sensor, bool]],
) -> None:
    if isinstance(data, list):
        for value in data:
            _collect_flex_config_sensors(value, path, is_output, references)
        return
    if not isinstance(data, dict):
        return
    for field, value in data.items():
        normalized_field = str(field).replace("_", "-")
        field_path = (*path, normalized_field)
        field_is_output = is_output or normalized_field in FLEX_CONFIG_OUTPUT_FIELDS
        if _is_sensor_reference_field(field) or _is_sensor_reference_list_field(field):
            for reference in _listify(value):
                if reference is None:
                    continue
                references.append(
                    (field_path, _load_sensor(reference), field_is_output)
                )
        else:
            _collect_flex_config_sensors(value, field_path, field_is_output, references)


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


# Request fields under which the scheduler records its results (see OUTPUT_SENSOR_FIELDS).
SCHEDULE_OUTPUT_FIELDS = OUTPUT_SENSOR_FIELDS


def flex_model_output_loader(
    flex_model: dict | list | None,
) -> dict[str, list[Sensor]]:
    """Extract the sensors a flex-model has the scheduler record results on, for permission checking.

    These are the sensors under an output field, and the power sensor of each device (its "sensor").
    """
    sensor_refs: dict[str, list[Sensor]] = {}
    label_path: tuple[str | int, ...] = ("json", "flex-model")
    for index, device_model in enumerate(_listify(flex_model)):
        if not isinstance(device_model, dict):
            continue
        device_path = (
            (*label_path, index) if isinstance(flex_model, list) else label_path
        )
        if "sensor" in device_model:
            _add_sensor_reference(
                sensor_refs, (*device_path, "sensor"), device_model["sensor"]
            )
        _collect_output_sensor_references(device_model, device_path, sensor_refs)
    return sensor_refs


def flex_context_output_loader(
    flex_context: dict | list | None,
) -> dict[str, list[Sensor]]:
    """Extract the sensors a flex-context has the scheduler record results on, for permission checking."""
    sensor_refs: dict[str, list[Sensor]] = {}
    _collect_output_sensor_references(
        flex_context, ("json", "flex-context"), sensor_refs
    )
    return sensor_refs


def _collect_output_sensor_references(
    data: Any,
    label_path: tuple[str | int, ...],
    sensor_refs: dict[str, list[Sensor]],
) -> None:
    if isinstance(data, dict):
        for field, value in data.items():
            field_path = (*label_path, field)
            if str(field).replace("_", "-") in SCHEDULE_OUTPUT_FIELDS:
                _collect_sensor_references(value, field_path, sensor_refs)
            else:
                _collect_output_sensor_references(value, field_path, sensor_refs)
    elif isinstance(data, list):
        for index, value in enumerate(data):
            _collect_output_sensor_references(value, (*label_path, index), sensor_refs)
