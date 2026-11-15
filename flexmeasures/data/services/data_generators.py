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
    """Return the sensors a data generator would read from and write to."""
    data_generator = copy(data_generator)
    data_generator._parameters = deserialized_parameters
    return {
        "input_sensors": data_generator.input_sensors,
        "output_sensors": data_generator.output_sensors,
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
