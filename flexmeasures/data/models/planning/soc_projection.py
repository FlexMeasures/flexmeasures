"""Projection of off-tick point-like SoC constraints onto scheduling ticks."""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal

import pandas as pd

from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.schemas.scheduling.utils import is_on_schedule_tick
from flexmeasures.utils.unit_utils import ur

logger = logging.getLogger(__name__)

SocBoundType = Literal["min", "max"]
SocProjectionTick = Literal["previous", "next"]

TimedEventList = list[dict[str, datetime | float]]
SocSpecification = TimedEventList | pd.Series | Sensor | ur.Quantity | None


@dataclass(frozen=True)
class SocProjectionRule:
    """One projected bound for an off-tick point-like SoC event.

    A rule only needs to state *which* bound lands on *which* surrounding
    scheduling tick; everything else follows from preserving reachability:

    - The capacity period runs from the tick to the event time (``previous``)
      or from the event time to the tick (``next``).
    - A bound is loosened by the energy the device can move through that period
      towards satisfying the original event: lower bounds by charging up to it
      (on the previous tick) or by discharging away from it (on the next tick),
      and upper bounds vice versa.
    - Lower bounds are loosened downwards, upper bounds upwards.
    """

    bound_type: SocBoundType
    tick: SocProjectionTick

    @property
    def uses_charging(self) -> bool:
        """Whether the bound is loosened by chargeable (rather than dischargeable) energy."""
        return (self.bound_type == "min") == (self.tick == "previous")

    @property
    def sign(self) -> int:
        """Lower bounds are loosened downwards (-1), upper bounds upwards (+1)."""
        return -1 if self.bound_type == "min" else +1


#: How each type of off-tick point-like SoC event is projected onto the
#: surrounding scheduling ticks (see :class:`SocProjectionRule`).
#: Off-tick ``soc-targets`` additionally become an exact target on the next
#: tick, and ``soc-at-start`` denotes a starting SoC known at an off-tick time
#: within the first scheduling interval; both are handled by their respective
#: entry points below.
SOC_PROJECTION_POLICIES: dict[str, tuple[SocProjectionRule, ...]] = {
    "soc-targets": (
        SocProjectionRule("min", "previous"),
        SocProjectionRule("max", "previous"),
    ),
    "soc-minima": (
        SocProjectionRule("min", "previous"),
        SocProjectionRule("min", "next"),
    ),
    "soc-maxima": (
        SocProjectionRule("max", "previous"),
        SocProjectionRule("max", "next"),
    ),
    "soc-at-start": (
        SocProjectionRule("min", "next"),
        SocProjectionRule("max", "next"),
    ),
}


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
    original_soc_events: SocSpecification,
    projected_soc_events: TimedEventList,
    field_name: str,
) -> SocSpecification:
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


@dataclass
class _SocProjection:
    """Working state for projecting the off-tick SoC events of one device.

    Bundles the device's capacities, efficiencies and global SoC limits, and
    accumulates the projected lower and upper bounds while rules are applied.
    """

    consumption_capacity: pd.Series
    production_capacity: pd.Series
    resolution: timedelta
    soc_min: float | None
    soc_max: float | None
    charging_efficiency: pd.Series | ur.Quantity | float | None = None
    discharging_efficiency: pd.Series | ur.Quantity | float | None = None
    minima: TimedEventList = field(default_factory=list)
    maxima: TimedEventList = field(default_factory=list)

    def reachable_energy(
        self, charging: bool, start: pd.Timestamp, end: pd.Timestamp
    ) -> float:
        """The energy (in MWh) the stock can move up (charging) or down (discharging)."""
        if charging:
            return _reachable_energy(
                self.consumption_capacity,
                start,
                end,
                self.resolution,
                efficiency=self.charging_efficiency,
                efficiency_affects_stock="multiply",
            )
        return _reachable_energy(
            self.production_capacity,
            start,
            end,
            self.resolution,
            efficiency=self.discharging_efficiency,
            efficiency_affects_stock="divide",
        )

    def apply_rule(
        self,
        rule: SocProjectionRule,
        soc_event: dict[str, datetime | float],
        event_time: pd.Timestamp,
    ) -> None:
        """Apply one projection rule to one off-tick SoC event.

        Computes the reachability-adjusted bound value, clamps it to the global
        SoC limits, and merges it into the projected minima or maxima (keeping
        the stricter bound if one already exists on the same tick).
        """
        previous_tick = event_time.floor(self.resolution)
        next_tick = event_time.ceil(self.resolution)
        if rule.tick == "previous":
            tick, period = previous_tick, (previous_tick, event_time)
        else:
            tick, period = next_tick, (event_time, next_tick)
        value = _soc_value_in_mwh(
            soc_event["value"]
        ) + rule.sign * self.reachable_energy(rule.uses_charging, *period)
        if rule.bound_type == "min":
            if self.soc_min is not None:
                value = max(self.soc_min, value)
            _add_soc_bound(self.minima, _soc_event_at(soc_event, tick, value), "min")
        else:
            if self.soc_max is not None:
                value = min(self.soc_max, value)
            _add_soc_bound(self.maxima, _soc_event_at(soc_event, tick, value), "max")

    def apply_policy(
        self,
        field_name: str,
        soc_event: dict[str, datetime | float],
        event_time: pd.Timestamp,
    ) -> None:
        """Apply all projection rules of the given policy to one off-tick SoC event."""
        for rule in SOC_PROJECTION_POLICIES[field_name]:
            self.apply_rule(rule, soc_event, event_time)


def _is_projectable(
    soc_event: dict[str, datetime | float], resolution: timedelta
) -> bool:
    """Whether the SoC event is point-like and falls between two scheduling ticks."""
    return soc_event["start"] == soc_event["end"] and not is_on_schedule_tick(
        soc_event["end"], resolution
    )


def project_off_tick_soc_constraints(
    soc_targets: SocSpecification,
    soc_maxima: SocSpecification,
    soc_minima: SocSpecification,
    consumption_capacity: pd.Series,
    production_capacity: pd.Series,
    resolution: timedelta,
    soc_min: ur.Quantity | float | None,
    soc_max: ur.Quantity | float | None,
    charging_efficiency: pd.Series | ur.Quantity | float | None = None,
    discharging_efficiency: pd.Series | ur.Quantity | float | None = None,
) -> tuple[SocSpecification, SocSpecification, SocSpecification]:
    """Project off-tick point-like SoC constraints onto scheduling ticks.

    The scheduler can only enforce constraints at its fixed scheduling resolution.
    Point-like ``soc-targets``, ``soc-minima`` and ``soc-maxima`` that fall between
    two scheduling ticks are therefore replaced by constraints on the previous and
    next tick that preserve reachability using the available charge and discharge
    capacity between the original event time and those ticks
    (see :data:`SOC_PROJECTION_POLICIES`).

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

    projection = _SocProjection(
        consumption_capacity=consumption_capacity,
        production_capacity=production_capacity,
        resolution=resolution,
        soc_min=_optional_soc_value_in_mwh(soc_min),
        soc_max=_optional_soc_value_in_mwh(soc_max),
        charging_efficiency=charging_efficiency,
        discharging_efficiency=discharging_efficiency,
        minima=copy.deepcopy(soc_minima) if isinstance(soc_minima, list) else [],
        maxima=copy.deepcopy(soc_maxima) if isinstance(soc_maxima, list) else [],
    )

    if isinstance(soc_targets, list):
        projected_targets = []
        for soc_target in soc_targets:
            if not _is_projectable(soc_target, resolution):
                projected_targets.append(copy.copy(soc_target))
                continue
            target_time = pd.Timestamp(soc_target["end"])
            # Exact target on the next tick, plus previous-tick bounds that keep
            # the target reachable at the original (off-tick) target time.
            projected_targets.append(
                _soc_event_at(
                    soc_target,
                    target_time.ceil(resolution),
                    _soc_value_in_mwh(soc_target["value"]),
                )
            )
            projection.apply_policy("soc-targets", soc_target, target_time)
    else:
        projected_targets = soc_targets

    for field_name, soc_events in (
        ("soc-minima", soc_minima),
        ("soc-maxima", soc_maxima),
    ):
        if not isinstance(soc_events, list):
            continue
        for soc_event in copy.deepcopy(soc_events):
            if _is_projectable(soc_event, resolution):
                projection.apply_policy(
                    field_name, soc_event, pd.Timestamp(soc_event["end"])
                )

    return (
        projected_targets,
        _projected_soc_events_or_original(soc_maxima, projection.maxima, "soc-maxima"),
        _projected_soc_events_or_original(soc_minima, projection.minima, "soc-minima"),
    )


def project_off_tick_soc_at_start(
    soc_at_start_time: datetime,
    soc_at_start: ur.Quantity | float,
    soc_maxima: SocSpecification,
    soc_minima: SocSpecification,
    schedule_start: datetime,
    consumption_capacity: pd.Series,
    production_capacity: pd.Series,
    resolution: timedelta,
    soc_min: ur.Quantity | float | None,
    soc_max: ur.Quantity | float | None,
    charging_efficiency: pd.Series | ur.Quantity | float | None = None,
    discharging_efficiency: pd.Series | ur.Quantity | float | None = None,
) -> tuple[SocSpecification, SocSpecification]:
    """Project an off-tick starting state of charge onto the next scheduling tick.

    When the starting SoC is known at a time ``t`` between the schedule start and
    the next scheduling tick ``n`` (e.g. because the ``state-of-charge`` field
    resolved to a measurement taken at ``t``), the SoC is assumed to hold from the
    schedule start until ``t`` (the device is not moving its stock before then), and
    the SoC at ``n`` is bounded by how much the device can (dis)charge between ``t``
    and ``n``:

    - an upper bound of ``soc_at_start`` plus the energy chargeable between ``t`` and ``n``,
    - a lower bound of ``soc_at_start`` minus the energy dischargeable between ``t`` and ``n``.

    Both bounds are clamped to the global ``soc-min``/``soc-max`` and merged into
    the given ``soc-maxima``/``soc-minima`` (the stricter bound wins on collisions).
    Known SoC times on a scheduling tick, or outside the first scheduling interval,
    leave the bounds unchanged.

    Returns ``(soc_maxima, soc_minima)``.
    """
    event_time = pd.Timestamp(soc_at_start_time)
    start = pd.Timestamp(schedule_start)
    if is_on_schedule_tick(event_time, resolution) or not (
        start < event_time < start + resolution
    ):
        return soc_maxima, soc_minima

    projection = _SocProjection(
        consumption_capacity=consumption_capacity,
        production_capacity=production_capacity,
        resolution=resolution,
        soc_min=_optional_soc_value_in_mwh(soc_min),
        soc_max=_optional_soc_value_in_mwh(soc_max),
        charging_efficiency=charging_efficiency,
        discharging_efficiency=discharging_efficiency,
        minima=copy.deepcopy(soc_minima) if isinstance(soc_minima, list) else [],
        maxima=copy.deepcopy(soc_maxima) if isinstance(soc_maxima, list) else [],
    )
    soc_event = {
        "start": event_time.to_pydatetime(),
        "end": event_time.to_pydatetime(),
        "value": _soc_value_in_mwh(soc_at_start),
    }
    projection.apply_policy("soc-at-start", soc_event, event_time)
    return (
        _projected_soc_events_or_original(soc_maxima, projection.maxima, "soc-maxima"),
        _projected_soc_events_or_original(soc_minima, projection.minima, "soc-minima"),
    )
