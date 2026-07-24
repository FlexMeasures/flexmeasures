from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from flexmeasures import Sensor


SOC_TIMED_EVENT_FIELDS = ("soc-targets", "soc-minima", "soc-maxima")


def is_on_schedule_tick(dt: datetime, resolution: timedelta) -> bool:
    timestamp = pd.Timestamp(dt)
    return timestamp == timestamp.floor(resolution)


def get_soc_constraint_resolution(
    schedule_resolution: timedelta | None,
    sensor: Sensor | None,
    default_resolution: timedelta,
) -> timedelta:
    if schedule_resolution not in (None, timedelta(0)):
        return schedule_resolution
    if sensor is not None and sensor.event_resolution != timedelta(0):
        return sensor.event_resolution
    return default_resolution


def should_project_off_tick_soc_constraints(sensor: Sensor | None) -> bool:
    return sensor is None or sensor.get_attribute("floor_datetimes_to_resolution", True)


def flex_model_has_off_tick_soc_constraints(
    flex_model: dict,
    resolution: timedelta | None,
) -> bool:
    if resolution in (None, timedelta(0)):
        return False

    for field_name in SOC_TIMED_EVENT_FIELDS:
        field_value = flex_model.get(
            field_name, flex_model.get(field_name.replace("-", "_"))
        )
        if not isinstance(field_value, list):
            continue
        for soc_event in field_value:
            if not isinstance(soc_event, dict):
                continue
            for timing_field in ("datetime", "start", "end"):
                if soc_event.get(timing_field) is None:
                    continue
                try:
                    is_on_tick = is_on_schedule_tick(
                        soc_event[timing_field], resolution
                    )
                except (TypeError, ValueError):
                    continue
                if not is_on_tick:
                    return True
    return False
