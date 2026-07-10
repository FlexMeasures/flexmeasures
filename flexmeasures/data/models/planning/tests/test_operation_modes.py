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
