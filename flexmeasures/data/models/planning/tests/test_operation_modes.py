"""Tests for power bands (S2 operation modes) in the device scheduler."""

import numpy as np
import pandas as pd

from flexmeasures.data.models.planning import FlowCommitment
from flexmeasures.data.models.planning.linear_optimization import device_scheduler
from flexmeasures.data.models.planning.utils import initialize_index


def _one_device_setup(stock_target: float):
    """One storage device charging towards a stock target over 4 hourly steps.

    Consumption is priced per step: cheap in steps 1 and 3, expensive in 0 and 2.
    """
    start = pd.Timestamp("2026-01-01T00:00+01")
    end = pd.Timestamp("2026-01-01T04:00+01")
    resolution = pd.Timedelta("PT1H")
    index = initialize_index(start=start, end=end, resolution=resolution)

    equals = pd.Series(np.nan, index=index)
    equals.iloc[-1] = stock_target
    device_constraints = [
        pd.DataFrame(
            {
                "min": 0,
                "max": 10,
                "equals": equals,
                "derivative min": 0,
                "derivative max": 0.5,
                "derivative equals": np.nan,
            },
            index=index,
        )
    ]
    ems_constraints = pd.DataFrame(
        {
            "derivative min": -10,
            "derivative max": 10,
        },
        index=index,
    )
    energy_commitment = FlowCommitment(
        name="energy",
        index=index,
        quantity=0,
        upwards_deviation_price=pd.Series([10, 1, 10, 1], index=index),
        downwards_deviation_price=0,
        device=pd.Series(0, index=index),
    )
    return device_constraints, ems_constraints, energy_commitment


def _schedule(device_power_bands=None, stock_target: float = 1.2):
    device_constraints, ems_constraints, energy_commitment = _one_device_setup(
        stock_target
    )
    schedule, costs, results, model = device_scheduler(
        device_constraints,
        ems_constraints,
        commitments=[energy_commitment],
        device_power_bands=device_power_bands,
    )
    assert "optimal" in str(results.solver.termination_condition)
    return schedule[0].values, costs


def _generator_setup(benefit_per_step: float):
    """One on/off "generator" device over 2 hourly steps.

    Running (consuming 0.5 MW) yields a fixed marginal benefit per step, modelled
    as a negative consumption price. There is no stock target, so the device is
    free to stay off. This isolates the trade-off between the per-step marginal
    benefit of running and a per-time running cost.
    """
    start = pd.Timestamp("2026-01-01T00:00+01")
    end = pd.Timestamp("2026-01-01T02:00+01")
    resolution = pd.Timedelta("PT1H")
    index = initialize_index(start=start, end=end, resolution=resolution)

    device_constraints = [
        pd.DataFrame(
            {
                "min": 0,
                "max": 10,
                "equals": np.nan,
                "derivative min": 0,
                "derivative max": 0.5,
                "derivative equals": np.nan,
            },
            index=index,
        )
    ]
    ems_constraints = pd.DataFrame(
        {"derivative min": -10, "derivative max": 10},
        index=index,
    )
    # Negative consumption price: each MW consumed for a step yields this benefit.
    energy_commitment = FlowCommitment(
        name="energy",
        index=index,
        quantity=0,
        upwards_deviation_price=pd.Series(-benefit_per_step, index=index),
        downwards_deviation_price=0,
        device=pd.Series(0, index=index),
    )
    return device_constraints, ems_constraints, energy_commitment


def test_operation_mode_running_cost_keeps_unit_idle():
    """A generator idles when its per-step marginal benefit is below the running cost.

    On band [0.5, 0.5] MW yields a benefit of 0.5 * 3 = 1.5 per step. The running
    cost is a rate of 2.0 per hour; over an hourly step that is 2.0 per step.
    Since 1.5 < 2.0, the unit-commitment optimum is to stay off. Objective is then
    exactly 0.
    """
    device_constraints, ems_constraints, energy_commitment = _generator_setup(
        benefit_per_step=3
    )
    schedule, costs, results, model = device_scheduler(
        device_constraints,
        ems_constraints,
        commitments=[energy_commitment],
        device_power_bands=[[(0, 0), (0.5, 0.5)]],
        device_band_running_costs=[[0.0, 2.0]],
    )
    assert "optimal" in str(results.solver.termination_condition)
    assert np.isclose(schedule[0].values, [0, 0]).all()
    assert np.isclose(costs, 0.0)


def test_operation_mode_running_cost_runs_and_is_charged():
    """A generator runs when its per-step benefit exceeds the running cost.

    On band [0.5, 0.5] MW yields a benefit of 0.5 * 3 = 1.5 per step. The running
    cost is a rate of 1.0 per hour; over an hourly step that is 1.0 per step.
    Since 1.5 > 1.0, the unit runs both steps.

    Hand-computed objective over 2 hourly steps (rate * duration = 1.0 * 1 h):
        energy benefit:  2 * (0.5 MW * -3) = -3.0
        running cost:    2 * (1.0/h * 1 h) = +2.0
        total:                               -1.0
    """
    device_constraints, ems_constraints, energy_commitment = _generator_setup(
        benefit_per_step=3
    )
    schedule, costs, results, model = device_scheduler(
        device_constraints,
        ems_constraints,
        commitments=[energy_commitment],
        device_power_bands=[[(0, 0), (0.5, 0.5)]],
        device_band_running_costs=[[0.0, 1.0]],
    )
    assert "optimal" in str(results.solver.termination_condition)
    assert np.isclose(schedule[0].values, [0.5, 0.5]).all()
    assert np.isclose(costs, -1.0)


def _forced_on_running_cost(resolution: pd.Timedelta) -> float:
    """Objective for a unit forced on for 2 wall-clock hours at a given resolution.

    The single band [0.5, 0.5] MW forces the unit on every step, there is no
    energy price, so the whole objective is the running cost. With a rate of
    1200/h over 2 hours the total must be 2400 regardless of resolution.
    """
    start = pd.Timestamp("2026-01-01T00:00+01")
    end = pd.Timestamp("2026-01-01T02:00+01")
    index = initialize_index(start=start, end=end, resolution=resolution)
    device_constraints = [
        pd.DataFrame(
            {
                "min": 0,
                "max": 10,
                "equals": np.nan,
                "derivative min": 0,
                "derivative max": 0.5,
                "derivative equals": np.nan,
            },
            index=index,
        )
    ]
    ems_constraints = pd.DataFrame(
        {"derivative min": -10, "derivative max": 10}, index=index
    )
    energy_commitment = FlowCommitment(
        name="energy",
        index=index,
        quantity=0,
        upwards_deviation_price=0,
        downwards_deviation_price=0,
        device=pd.Series(0, index=index),
    )
    schedule, costs, results, model = device_scheduler(
        device_constraints,
        ems_constraints,
        commitments=[energy_commitment],
        device_power_bands=[[(0.5, 0.5)]],  # single band: forced on
        device_band_running_costs=[[1200.0]],  # 1200 currency/hour
    )
    assert "optimal" in str(results.solver.termination_condition)
    return costs


def test_operation_mode_running_cost_is_resolution_independent():
    """The running cost of a fixed on-duration is identical across resolutions.

    A rate of 1200/h applied to a unit forced on for 2 hours totals 2400,
    whether the horizon is discretised hourly or in quarter-hours.
    """
    hourly = _forced_on_running_cost(pd.Timedelta("PT1H"))
    quarter_hourly = _forced_on_running_cost(pd.Timedelta("PT15M"))
    assert np.isclose(hourly, 2400.0)
    assert np.isclose(quarter_hourly, 2400.0)
    assert np.isclose(hourly, quarter_hourly)


def test_device_scheduler_without_bands_uses_fractional_power():
    """Sanity check: without bands, the cheapest plan uses fractional power (0.2)."""
    values, costs = _schedule(stock_target=1.2)
    # Cheap steps maxed out (0.5 each); the 0.2 remainder lands in the expensive steps
    assert np.isclose(values[1], 0.5) and np.isclose(values[3], 0.5)
    assert np.isclose(values[0] + values[2], 0.2)
    assert np.isclose(costs, 1.0 + 2.0)


def test_device_scheduler_with_on_off_bands():
    """A device confined to {0} U {0.5} runs full-on where cheap, never fractionally."""
    values, costs = _schedule(
        device_power_bands=[[(0, 0), (0.5, 0.5)]], stock_target=1.0
    )
    assert np.isclose(values, [0, 0.5, 0, 0.5]).all()
    assert np.isclose(costs, 1.0)


def test_device_scheduler_with_min_power_band():
    """A device confined to {0} U [0.4, 0.5] cannot run below its minimum power.

    To reach the 1.2 stock target, running the two cheap steps at 0.4 plus one
    expensive step at 0.4 (cost 4.8) beats maxing out the cheap steps, because
    the 0.2 remainder would have to be rounded up to the 0.4 band minimum
    (0.5 + 0.5 + 0.4 sums to 1.4, overshooting the exact stock target).
    """
    values, costs = _schedule(
        device_power_bands=[[(0, 0), (0.4, 0.5)]], stock_target=1.2
    )
    for v in values:
        assert np.isclose(v, 0) or (0.4 - 1e-6 <= v <= 0.5 + 1e-6)
    assert np.isclose(values.sum(), 1.2)
    assert np.isclose(sorted(values), [0, 0.4, 0.4, 0.4]).all()
    assert np.isclose(costs, 4.8)
