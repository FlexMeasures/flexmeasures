"""How a forecaster's config describes the sensors it reads, including the one it forecasts.

A forecaster's config says which sources to train on and how to clean what it reads.
The sensor being forecast is named in the forecast parameters rather than in the config,
so a config that wants to say the same about that sensor writes ``"auto"`` in place of its ID.
"""

from __future__ import annotations

from typing import Any

from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.schemas.forecasting.references import AutoSensorReference
from flexmeasures.data.schemas.sensors import SensorReference

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
