"""Authorization helpers shared by data-generator entry points."""

from __future__ import annotations

from copy import copy

from werkzeug.exceptions import Forbidden

from flexmeasures.auth.policy import (
    check_access,
    user_has_admin_access,
    user_matches_principals,
)
from flexmeasures.data.models.data_sources import DataGenerator
from flexmeasures.data.models.time_series import Sensor


def resolve_data_generator_sensors(
    data_generator: DataGenerator, deserialized_parameters: dict
) -> dict[str, list[Sensor]]:
    """Return the sensors a data generator would read from and write to.

    The sensors it writes to include those it records annotations on (its `annotated_sensors`),
    as a sensor grants annotating it to the same users as recording data on it,
    and an automation may only do either on the sensors it was checked against.
    """
    data_generator = copy(data_generator)
    data_generator._parameters = deserialized_parameters
    output_sensors = list(data_generator.output_sensors)
    output_ids = {sensor.id for sensor in output_sensors}
    output_sensors += [
        sensor
        for sensor in data_generator.annotated_sensors
        if sensor.id not in output_ids
    ]
    return {
        "input_sensors": data_generator.input_sensors,
        "output_sensors": output_sensors,
    }


def check_sensor_access(
    input_sensors: list[Sensor], output_sensors: list[Sensor]
) -> None:
    """Require read access to inputs and create-children access to outputs."""
    for sensors, permission, action in (
        (input_sensors, "read", "read data from"),
        (output_sensors, "create-children", "record data on"),
    ):
        for sensor in sensors:
            try:
                check_access(sensor, permission)
            except Forbidden as exc:
                exc.api_message = (
                    f"You cannot request this computation because it would {action}"
                    f" sensor {sensor.id}, which you cannot {action} yourself."
                )
                raise


def annotation_sources(data_generator: DataGenerator | None) -> list:
    """Return the accounts, assets and sensors whose annotations a data generator reads.

    Forecasters read them through the ``annotation-regressors`` field of their config,
    which turns those annotations into a 0/1 regressor.
    """
    config = getattr(data_generator, "_config", None) or {}
    sources = []
    for regressor in config.get("annotation_regressors") or []:
        if not isinstance(regressor, dict):
            continue
        for key in ("account", "asset", "sensor"):
            source = regressor.get(key)
            if source is not None and not isinstance(source, (int, str)):
                sources.append(source)
    return sources


def check_annotation_source_access(sources: list) -> None:
    """Require read access to every account, asset or sensor whose annotations are used."""
    for source in sources:
        try:
            check_access(source, "read")
        except Forbidden as exc:
            kind = {
                "Account": "account",
                "GenericAsset": "asset",
                "Sensor": "sensor",
            }.get(type(source).__name__, "entity")
            exc.api_message = (
                "You cannot request this computation because it would read the annotations of"
                f" {kind} {source.id}, which you cannot read yourself."
            )
            raise


def check_sensor_access_of_user(
    user, input_sensors: list[Sensor], output_sensors: list[Sensor]
) -> None:
    """Require a given user (not necessarily the current one) to have read access to inputs and create-children access to outputs.

    For use where no request context holds the user, as in a worker running a job that a user triggered.
    """
    if user is None or not user.active:
        raise Forbidden("The user who triggered this job is missing or inactive.")
    for sensors, permission, action in (
        (input_sensors, "read", "read data from"),
        (output_sensors, "create-children", "record data on"),
    ):
        for sensor in sensors:
            if not user_has_admin_access(
                user, permission
            ) and not user_matches_principals(
                user, sensor.__acl__().get(permission, [])
            ):
                raise Forbidden(
                    f"The user who triggered this job (user {user.id}) cannot {action} sensor {sensor.id}."
                )
