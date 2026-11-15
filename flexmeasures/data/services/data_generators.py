"""Authorization helpers shared by data-generator entry points."""

from __future__ import annotations

from werkzeug.exceptions import Forbidden

from flexmeasures.auth.policy import check_access
from flexmeasures.data.models.data_sources import DataGenerator
from flexmeasures.data.models.time_series import Sensor


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
