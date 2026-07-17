"""Projection of off-tick point-like SoC constraints onto scheduling ticks."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

import pandas as pd

from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.schemas.scheduling.utils import is_on_schedule_tick
from flexmeasures.utils.unit_utils import ur


SocBoundType = Literal["min", "max"]
SocProjectionTick = Literal["previous", "next"]
SocCapacityType = Literal["consumption", "production"]
SocCapacityPeriod = Literal["before", "after"]


@dataclass(frozen=True)
class SocProjectionRule:
    bound_type: SocBoundType
    tick: SocProjectionTick
    capacity: SocCapacityType
    period: SocCapacityPeriod
    sign: int


SOC_PROJECTION_POLICIES = {
    "soc-targets": (
        SocProjectionRule("min", "previous", "consumption", "before", -1),
        SocProjectionRule("max", "previous", "production", "before", +1),
    ),
    "soc-minima": (
        SocProjectionRule("min", "previous", "consumption", "before", -1),
        SocProjectionRule("min", "next", "production", "after", -1),
    ),
    "soc-maxima": (
        SocProjectionRule("max", "previous", "production", "before", +1),
        SocProjectionRule("max", "next", "consumption", "after", +1),
    ),
}


def _soc_value_in_mwh(value: ur.Quantity | float | int) -> float:
    if isinstance(value, ur.Quantity):
        return value.to("MWh").magnitude
    return float(value)


def _optional_soc_value_in_mwh(value: ur.Quantity | float | int | None) -> float | None:
    if value is None:
        return None
    return _soc_value_in_mwh(value)


def _clamp_soc_min(value: float, soc_min: float | None) -> float:
    return value if soc_min is None else max(soc_min, value)


def _clamp_soc_max(value: float, soc_max: float | None) -> float:
    return value if soc_max is None else min(soc_max, value)


def _soc_event_at(
    soc_event: dict[str, datetime | float],
    dt: pd.Timestamp,
    value: float,
) -> dict[str, datetime | float]:
    shifted_event = copy.copy(soc_event)
    shifted_event["value"] = value
    shifted_event["start"] = dt.to_pydatetime()
    shifted_event["end"] = dt.to_pydatetime()
    if "datetime" in shifted_event:
        shifted_event["datetime"] = dt.to_pydatetime()
    shifted_event.pop("duration", None)
    return shifted_event


def _energy_capacity_between(
    capacity: pd.Series,
    start: pd.Timestamp,
    end: pd.Timestamp,
    resolution: timedelta,
) -> float:
    if end <= start:
        return 0

    if capacity.index.tz is not None:
        start = start.tz_convert(capacity.index.tz)
        end = end.tz_convert(capacity.index.tz)

    capacity = capacity.astype(float).fillna(0)
    tick = start.floor(resolution)
    energy = 0.0
    while tick < end:
        next_tick = tick + resolution
        overlap_start = max(start, tick)
        overlap_end = min(end, next_tick)
        if overlap_end > overlap_start and tick in capacity.index:
            energy += float(capacity.loc[tick]) * (
                (overlap_end - overlap_start) / pd.Timedelta(hours=1)
            )
        tick = next_tick
    return energy


def _tick_for_projection_rule(
    rule: SocProjectionRule,
    previous_tick: pd.Timestamp,
    next_tick: pd.Timestamp,
) -> pd.Timestamp:
    return previous_tick if rule.tick == "previous" else next_tick


def _capacity_for_projection_rule(
    rule: SocProjectionRule,
    consumption_capacity: pd.Series,
    production_capacity: pd.Series,
) -> pd.Series:
    return (
        consumption_capacity if rule.capacity == "consumption" else production_capacity
    )


def _capacity_period_for_projection_rule(
    rule: SocProjectionRule,
    previous_tick: pd.Timestamp,
    event_time: pd.Timestamp,
    next_tick: pd.Timestamp,
) -> tuple[pd.Timestamp, pd.Timestamp]:
    if rule.period == "before":
        return previous_tick, event_time
    return event_time, next_tick


def _clamp_projected_soc_value(
    value: float,
    rule: SocProjectionRule,
    soc_min: float | None,
    soc_max: float | None,
) -> float:
    if rule.bound_type == "min":
        return _clamp_soc_min(value, soc_min)
    return _clamp_soc_max(value, soc_max)


def _add_projected_soc_bound(
    projected_minima: list[dict[str, datetime | float]],
    projected_maxima: list[dict[str, datetime | float]],
    soc_event: dict[str, datetime | float],
    rule: SocProjectionRule,
    event_time: pd.Timestamp,
    previous_tick: pd.Timestamp,
    next_tick: pd.Timestamp,
    consumption_capacity: pd.Series,
    production_capacity: pd.Series,
    resolution: timedelta,
    soc_min: float | None,
    soc_max: float | None,
) -> None:
    capacity_start, capacity_end = _capacity_period_for_projection_rule(
        rule, previous_tick, event_time, next_tick
    )
    capacity = _capacity_for_projection_rule(
        rule, consumption_capacity, production_capacity
    )
    projected_value = _soc_value_in_mwh(soc_event["value"]) + rule.sign * (
        _energy_capacity_between(capacity, capacity_start, capacity_end, resolution)
    )
    projected_soc_events = (
        projected_minima if rule.bound_type == "min" else projected_maxima
    )
    _add_soc_bound(
        projected_soc_events,
        _soc_event_at(
            soc_event,
            _tick_for_projection_rule(rule, previous_tick, next_tick),
            _clamp_projected_soc_value(projected_value, rule, soc_min, soc_max),
        ),
        bound_type=rule.bound_type,
    )


def _add_soc_bound(
    soc_events: list[dict[str, datetime | float]],
    soc_event: dict[str, datetime | float],
    bound_type: str,
) -> None:
    for existing_event in soc_events:
        if existing_event.get("start") == soc_event.get("start") and existing_event.get(
            "end"
        ) == soc_event.get("end"):
            existing_value = _soc_value_in_mwh(existing_event["value"])
            soc_value = _soc_value_in_mwh(soc_event["value"])
            existing_event["value"] = (
                max(existing_value, soc_value)
                if bound_type == "min"
                else min(existing_value, soc_value)
            )
            return
    soc_events.append(soc_event)


def _projected_soc_events_or_original(
    original_soc_events: (
        list[dict[str, datetime | float]] | pd.Series | Sensor | ur.Quantity | None
    ),
    projected_soc_events: list[dict[str, datetime | float]],
) -> list[dict[str, datetime | float]] | pd.Series | Sensor | ur.Quantity | None:
    if isinstance(original_soc_events, list):
        return projected_soc_events
    if original_soc_events is None and projected_soc_events:
        return projected_soc_events
    return original_soc_events


def project_off_tick_soc_constraints(
    soc_targets: (
        list[dict[str, datetime | float]] | pd.Series | Sensor | ur.Quantity | None
    ),
    soc_maxima: (
        list[dict[str, datetime | float]] | pd.Series | Sensor | ur.Quantity | None
    ),
    soc_minima: (
        list[dict[str, datetime | float]] | pd.Series | Sensor | ur.Quantity | None
    ),
    consumption_capacity: pd.Series,
    production_capacity: pd.Series,
    resolution: timedelta,
    soc_min: ur.Quantity | float | None,
    soc_max: ur.Quantity | float | None,
) -> tuple[
    list[dict[str, datetime | float]] | pd.Series | Sensor | ur.Quantity | None,
    list[dict[str, datetime | float]] | pd.Series | Sensor | ur.Quantity | None,
    list[dict[str, datetime | float]] | pd.Series | Sensor | ur.Quantity | None,
]:
    """Project off-tick point-like SoC constraints onto scheduling ticks.

    The scheduler can only enforce constraints at its fixed scheduling resolution.
    Point-like ``soc-targets``, ``soc-minima`` and ``soc-maxima`` that fall between
    two scheduling ticks are therefore replaced by constraints on the previous and
    next tick that preserve reachability using the available charge and discharge
    capacity between the original event time and those ticks.

    ``soc-targets`` are projected to an exact target on the next tick, plus
    capacity-adjusted lower and upper bounds on the previous tick. ``soc-minima``
    become lower bounds on both surrounding ticks, and ``soc-maxima`` become upper
    bounds on both surrounding ticks. If multiple projected bounds land on the same
    tick, the stricter lower or upper bound is kept.

    Returns ``(soc_targets, soc_maxima, soc_minima)`` with projected list-based
    timed events. Non-list specifications such as sensors, series, fixed
    quantities, or ``None`` are returned unchanged unless projected bounds need to
    be added to a missing list.
    """

    if not any(
        isinstance(soc_events, list) and soc_events
        for soc_events in (soc_targets, soc_maxima, soc_minima)
    ):
        return soc_targets, soc_maxima, soc_minima

    projected_minima = copy.deepcopy(soc_minima) if isinstance(soc_minima, list) else []
    projected_maxima = copy.deepcopy(soc_maxima) if isinstance(soc_maxima, list) else []

    soc_min_value = _optional_soc_value_in_mwh(soc_min)
    soc_max_value = _optional_soc_value_in_mwh(soc_max)

    if isinstance(soc_targets, list):
        projected_targets = []
        for soc_target in soc_targets:
            if soc_target["start"] != soc_target["end"] or is_on_schedule_tick(
                soc_target["end"], resolution
            ):
                projected_targets.append(copy.copy(soc_target))
                continue

            target_time = pd.Timestamp(soc_target["end"])
            previous_tick = target_time.floor(resolution)
            next_tick = target_time.ceil(resolution)
            target_value = _soc_value_in_mwh(soc_target["value"])

            projected_targets.append(_soc_event_at(soc_target, next_tick, target_value))
            for rule in SOC_PROJECTION_POLICIES["soc-targets"]:
                _add_projected_soc_bound(
                    projected_minima,
                    projected_maxima,
                    soc_target,
                    rule,
                    target_time,
                    previous_tick,
                    next_tick,
                    consumption_capacity,
                    production_capacity,
                    resolution,
                    soc_min_value,
                    soc_max_value,
                )
    else:
        projected_targets = soc_targets

    for field_name, soc_events in (
        ("soc-minima", soc_minima),
        ("soc-maxima", soc_maxima),
    ):
        if not isinstance(soc_events, list):
            continue
        for soc_event in copy.deepcopy(soc_events):
            if soc_event["start"] != soc_event["end"] or is_on_schedule_tick(
                soc_event["end"], resolution
            ):
                continue

            event_time = pd.Timestamp(soc_event["end"])
            previous_tick = event_time.floor(resolution)
            next_tick = event_time.ceil(resolution)
            for rule in SOC_PROJECTION_POLICIES[field_name]:
                _add_projected_soc_bound(
                    projected_minima,
                    projected_maxima,
                    soc_event,
                    rule,
                    event_time,
                    previous_tick,
                    next_tick,
                    consumption_capacity,
                    production_capacity,
                    resolution,
                    soc_min_value,
                    soc_max_value,
                )

    return (
        projected_targets,
        _projected_soc_events_or_original(soc_maxima, projected_maxima),
        _projected_soc_events_or_original(soc_minima, projected_minima),
    )
