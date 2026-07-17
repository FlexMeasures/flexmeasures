"""Projection of off-tick point-like SoC constraints onto scheduling ticks."""

from __future__ import annotations

import copy
import logging
from datetime import datetime, timedelta

import pandas as pd

from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.schemas.scheduling.utils import is_on_schedule_tick
from flexmeasures.utils.unit_utils import ur

logger = logging.getLogger(__name__)


def _soc_value_in_mwh(value: ur.Quantity | float | int) -> float:
    """Return the SoC value as a plain float in MWh."""
    if isinstance(value, ur.Quantity):
        return value.to("MWh").magnitude
    return float(value)


def _optional_soc_value_in_mwh(value: ur.Quantity | float | int | None) -> float | None:
    """Return the SoC value as a plain float in MWh, passing through None."""
    if value is None:
        return None
    return _soc_value_in_mwh(value)


def _clamp_soc_min(value: float, soc_min: float | None) -> float:
    """Raise a projected lower bound to the storage's global soc-min, if defined."""
    return value if soc_min is None else max(soc_min, value)


def _clamp_soc_max(value: float, soc_max: float | None) -> float:
    """Lower a projected upper bound to the storage's global soc-max, if defined."""
    return value if soc_max is None else min(soc_max, value)


def _soc_event_at(
    soc_event: dict[str, datetime | float],
    dt: pd.Timestamp,
    value: float,
) -> dict[str, datetime | float]:
    """Return a copy of a point-like SoC event, moved to the given tick with the given value.

    All timing fields are set to the tick (any 'duration' is dropped), so the result
    remains a point-like (instantaneous) event.
    """
    shifted_event = copy.copy(soc_event)
    shifted_event["value"] = value
    shifted_event["start"] = dt.to_pydatetime()
    shifted_event["end"] = dt.to_pydatetime()
    if "datetime" in shifted_event:
        shifted_event["datetime"] = dt.to_pydatetime()
    shifted_event.pop("duration", None)
    return shifted_event


def _efficiency_at(
    efficiency: pd.Series | ur.Quantity | float | None,
    tick: pd.Timestamp,
) -> float:
    """Return the (dis)charging efficiency at the given tick as a plain float.

    Efficiencies may be given as a series (indexed by tick start), a fixed
    dimensionless quantity, or a plain number. Missing values default to 1.
    """
    if efficiency is None:
        return 1
    if isinstance(efficiency, pd.Series):
        if efficiency.index.tz is not None:
            tick = tick.tz_convert(efficiency.index.tz)
        value = efficiency.get(tick)
        if value is None or pd.isna(value):
            return 1
        return float(value)
    if isinstance(efficiency, ur.Quantity):
        return float(efficiency.to("dimensionless").magnitude)
    return float(efficiency)


def _reachable_energy(
    capacity: pd.Series,
    start: pd.Timestamp,
    end: pd.Timestamp,
    resolution: timedelta,
    efficiency: pd.Series | ur.Quantity | float | None = None,
    efficiency_affects_stock: str = "multiply",
) -> float:
    """Compute by how much energy (in MWh) the device can move its stock between two times.

    The period from ``start`` to ``end`` always lies within a single scheduling
    tick (from the tick just before an off-tick event to the event, or from the
    event to the tick just after it), so the given power capacity series (in MW,
    indexed by tick start at the given resolution) applies at a single constant
    value. A missing capacity value counts as zero (conservative: the projected
    bound then sticks close to the original event value).

    The capacity limits the power exchanged with the grid, while the projected
    bounds concern the stock (SoC). Charging at power P raises the stock at rate
    P * charging_efficiency (``efficiency_affects_stock="multiply"``; note that a
    charging efficiency can exceed 1, e.g. a heat pump's COP), while discharging
    at power P lowers the stock at rate P / discharging_efficiency
    (``efficiency_affects_stock="divide"``).
    """
    if end <= start:
        return 0
    tick = start.floor(resolution)
    if capacity.index.tz is not None:
        tick = tick.tz_convert(capacity.index.tz)
    capacity_in_mw = capacity.get(tick)
    if capacity_in_mw is None or pd.isna(capacity_in_mw):
        return 0
    efficiency_value = _efficiency_at(efficiency, tick)
    stock_rate_in_mw = float(capacity_in_mw)
    if efficiency_affects_stock == "multiply":
        stock_rate_in_mw *= efficiency_value
    elif efficiency_value != 0:
        stock_rate_in_mw /= efficiency_value
    else:
        # A zero discharging efficiency means the stock can drop arbitrarily
        # fast without producing any power, so the bound becomes unbounded.
        stock_rate_in_mw = float("inf")
    return stock_rate_in_mw * ((end - start) / pd.Timedelta(hours=1))


def _add_soc_bound(
    soc_events: list[dict[str, datetime | float]],
    soc_event: dict[str, datetime | float],
    bound_type: str,
) -> None:
    """Add a SoC bound to a list of timed events, merging bounds on the same period.

    If an event with the same start and end already exists, the stricter bound wins:
    the maximum of two lower bounds, or the minimum of two upper bounds.
    """
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
    field_name: str,
) -> list[dict[str, datetime | float]] | pd.Series | Sensor | ur.Quantity | None:
    """Choose between the projected event list and the original specification.

    Only list-based (or missing) specifications can absorb projected bounds;
    sensors, series and fixed quantities are returned unchanged. If projected
    bounds had to be dropped as a result, a warning is logged.
    """
    if isinstance(original_soc_events, list):
        return projected_soc_events
    if original_soc_events is None and projected_soc_events:
        return projected_soc_events
    if projected_soc_events:
        logger.warning(
            f"Dropping {len(projected_soc_events)} projected SoC bound(s): "
            f"the '{field_name}' field is not given as a list of timed events, "
            f"so projected bounds cannot be merged into it."
        )
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
    charging_efficiency: pd.Series | ur.Quantity | float | None = None,
    discharging_efficiency: pd.Series | ur.Quantity | float | None = None,
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

    For an off-tick event with value ``v`` at time ``t``, between previous tick ``p``
    and next tick ``n``:

    - ``soc-targets`` become an exact target ``v`` on ``n``, plus bounds on ``p`` that
      keep the target reachable at ``t``: a lower bound of ``v`` minus the energy that
      can still be charged between ``p`` and ``t``, and an upper bound of ``v`` plus
      the energy that can still be discharged between ``p`` and ``t``.
    - ``soc-minima`` become lower bounds on both surrounding ticks: on ``p``, ``v``
      minus the energy that can be charged between ``p`` and ``t``; on ``n``, ``v``
      minus the energy that can be discharged between ``t`` and ``n``.
    - ``soc-maxima`` become upper bounds on both surrounding ticks: on ``p``, ``v``
      plus the energy that can be discharged between ``p`` and ``t``; on ``n``, ``v``
      plus the energy that can be charged between ``t`` and ``n``.

    The reachable energy accounts for the (dis)charging efficiencies: charging at
    grid power P moves the stock at rate P * charging_efficiency (which can exceed
    1, e.g. a heat pump's COP), and discharging at grid power P moves the stock at
    rate P / discharging_efficiency.

    If multiple projected bounds land on the same tick, the stricter lower or upper
    bound is kept. Projected bounds are clamped to the global ``soc-min``/``soc-max``.

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

    def add_min_bound(soc_event: dict, tick: pd.Timestamp, value: float) -> None:
        _add_soc_bound(
            projected_minima,
            _soc_event_at(soc_event, tick, _clamp_soc_min(value, soc_min_value)),
            bound_type="min",
        )

    def add_max_bound(soc_event: dict, tick: pd.Timestamp, value: float) -> None:
        _add_soc_bound(
            projected_maxima,
            _soc_event_at(soc_event, tick, _clamp_soc_max(value, soc_max_value)),
            bound_type="max",
        )

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
            chargeable = _reachable_energy(
                consumption_capacity,
                previous_tick,
                target_time,
                resolution,
                efficiency=charging_efficiency,
                efficiency_affects_stock="multiply",
            )
            dischargeable = _reachable_energy(
                production_capacity,
                previous_tick,
                target_time,
                resolution,
                efficiency=discharging_efficiency,
                efficiency_affects_stock="divide",
            )

            # Exact target on the next tick, plus previous-tick bounds that keep
            # the target reachable at the original (off-tick) target time.
            projected_targets.append(_soc_event_at(soc_target, next_tick, target_value))
            add_min_bound(soc_target, previous_tick, target_value - chargeable)
            add_max_bound(soc_target, previous_tick, target_value + dischargeable)
    else:
        projected_targets = soc_targets

    if isinstance(soc_minima, list):
        for soc_event in copy.deepcopy(soc_minima):
            if soc_event["start"] != soc_event["end"] or is_on_schedule_tick(
                soc_event["end"], resolution
            ):
                continue

            event_time = pd.Timestamp(soc_event["end"])
            previous_tick = event_time.floor(resolution)
            next_tick = event_time.ceil(resolution)
            minimum = _soc_value_in_mwh(soc_event["value"])

            # Lower bounds on both surrounding ticks that preserve whether the
            # requested minimum can still be reached at the original event time.
            add_min_bound(
                soc_event,
                previous_tick,
                minimum
                - _reachable_energy(
                    consumption_capacity,
                    previous_tick,
                    event_time,
                    resolution,
                    efficiency=charging_efficiency,
                    efficiency_affects_stock="multiply",
                ),
            )
            add_min_bound(
                soc_event,
                next_tick,
                minimum
                - _reachable_energy(
                    production_capacity,
                    event_time,
                    next_tick,
                    resolution,
                    efficiency=discharging_efficiency,
                    efficiency_affects_stock="divide",
                ),
            )

    if isinstance(soc_maxima, list):
        for soc_event in copy.deepcopy(soc_maxima):
            if soc_event["start"] != soc_event["end"] or is_on_schedule_tick(
                soc_event["end"], resolution
            ):
                continue

            event_time = pd.Timestamp(soc_event["end"])
            previous_tick = event_time.floor(resolution)
            next_tick = event_time.ceil(resolution)
            maximum = _soc_value_in_mwh(soc_event["value"])

            # Upper bounds on both surrounding ticks that preserve whether the
            # requested maximum can still be respected at the original event time.
            add_max_bound(
                soc_event,
                previous_tick,
                maximum
                + _reachable_energy(
                    production_capacity,
                    previous_tick,
                    event_time,
                    resolution,
                    efficiency=discharging_efficiency,
                    efficiency_affects_stock="divide",
                ),
            )
            add_max_bound(
                soc_event,
                next_tick,
                maximum
                + _reachable_energy(
                    consumption_capacity,
                    event_time,
                    next_tick,
                    resolution,
                    efficiency=charging_efficiency,
                    efficiency_affects_stock="multiply",
                ),
            )

    return (
        projected_targets,
        _projected_soc_events_or_original(soc_maxima, projected_maxima, "soc-maxima"),
        _projected_soc_events_or_original(soc_minima, projected_minima, "soc-minima"),
    )
