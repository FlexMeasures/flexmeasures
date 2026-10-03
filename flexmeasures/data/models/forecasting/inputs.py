"""How a forecaster's config describes the sensors it reads, including the one it forecasts.

A forecaster's config says which sources to train on and how to clean what it reads.
The sensor being forecast is named in the forecast parameters rather than in the config,
so a config that wants to say the same about that sensor writes ``"auto"`` in place of its ID.
"""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.schemas.forecasting.references import (
    AUTO_SENSOR,
    AutoSensorReference,
)
from flexmeasures.data.schemas.sensors import SensorReference, SensorReferenceSchema

if TYPE_CHECKING:
    from flexmeasures.data.models.data_sources import DataSource

#: The regressor lists a config entry for the sensor being forecast may appear in.
REGRESSOR_FIELDS = ("past_regressors", "future_regressors")


def _is_target_entry(
    entry: Sensor | SensorReference | AutoSensorReference, target_sensor: Sensor
) -> bool:
    """Whether a config entry describes the sensor being forecast."""
    if isinstance(entry, AutoSensorReference):
        return True
    return getattr(entry, "id", None) == target_sensor.id


def resolve_forecast_inputs(
    config: dict[str, Any], target_sensor: Sensor
) -> tuple[dict[str, Any], Sensor | SensorReference]:
    """Resolve a config against the sensor being forecast.

    The config holds one entry per sensor the forecaster reads.
    The sensor being forecast is read as well, as the labels the model learns from and as its own lags,
    so an entry naming it says how to read it rather than adding it to the model a second time:
    such an entry is taken out of the regressor lists and describes the target instead.
    Where several entries name it, the last one wins.

    :param config:        The forecaster's config, as loaded.
    :param target_sensor: The sensor the forecast is made for.
    :returns:             The config to run with, whose regressor lists name concrete sensors, and the target as its entry describes it.
    """
    resolved = dict(config)
    target: Sensor | SensorReference = target_sensor
    for field_name in REGRESSOR_FIELDS:
        kept = []
        for entry in config.get(field_name) or []:
            if _is_target_entry(entry, target_sensor):
                target = (
                    entry.resolve(target_sensor)
                    if isinstance(entry, AutoSensorReference)
                    else entry
                )
                continue
            kept.append(entry)
        resolved[field_name] = kept
    return resolved, target


def _target_qualifiers(target: Sensor | SensorReference) -> dict[str, Any]:
    """The source filters and cleaning bounds a target reference carries, as a config entry would write them."""
    if not isinstance(target, SensorReference):
        return {}
    dumped = SensorReferenceSchema().dump(target)
    # A dumped reference spells out the filters it does not set, which a config entry would leave out.
    return {
        key: value
        for key, value in dumped.items()
        if key != "sensor" and value not in (None, {}, [])
    }


def fold_target_qualifiers_into_config(
    config: dict[str, Any],
    parameters: dict[str, Any],
    recorded_source: DataSource | None = None,
) -> bool:
    """Move source filters and cleaning bounds off the target in the parameters, into the config.

    Both were briefly settable on the target in the forecast parameters, where they never reached the data source's data-generator attributes.
    A payload that still carries them keeps working: the qualifiers move to a config entry naming ``"auto"``, and the parameters name the sensor alone.

    Where the forecaster was set up from a data source that already exists, moving them is refused instead.
    That source records the config as it was, and nothing here can change what it records:
    the forecast would be computed with the qualifiers and attributed to a source saying it ran without them,
    which is the very gap this release closes. Such a payload is stored, so it would run that way again on every recurrence.

    :param config:          The forecaster's config, mutated in place where the parameters carry qualifiers.
    :param parameters:      The forecast parameters, whose target is replaced by the sensor it wraps.
    :param recorded_source: The data source the forecaster was set up from, where it was set up from one.
    :returns:               Whether anything was moved.
    :raises ValueError:     if the parameters carry qualifiers while the config is already recorded on a data source.
    """
    target = parameters.get("sensor")
    qualifiers = _target_qualifiers(target)
    if not qualifiers:
        return False
    if recorded_source is not None:
        raise ValueError(
            f"The forecast parameters qualify their target sensor with {', '.join(sorted(qualifiers))},"
            f" while the forecaster is set up from data source {recorded_source.id}, whose configuration says nothing of them."
            f" Moving them into that configuration is not possible, as the source records it as it was,"
            f" so the forecast would be computed under qualifiers its own source does not report."
            f" Recreate this forecaster with the qualifiers in its configuration, as an entry naming '{AUTO_SENSOR}'."
        )

    config["past_regressors"] = list(config.get("past_regressors") or []) + [
        AutoSensorReference(qualifiers)
    ]
    parameters["sensor"] = target.sensor
    logging.warning(
        f"The forecast parameters qualify their target sensor with {', '.join(sorted(qualifiers))}."
        f" These belong in the forecaster's config, as an entry naming '{AUTO_SENSOR}', and have been moved there."
        " Configured there, they describe the forecaster itself, and are recorded on its data source."
    )
    return True
