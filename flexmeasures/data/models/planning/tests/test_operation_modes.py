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


def _cogeneration_setup(
    stock_target: float | None,
    electricity_up_price,
    gas_up_price: float,
):
    """A unit-committed affine cogeneration unit as a multi-commodity operation mode.

    Three devices share one operation-mode binary carried by the (banded) electricity
    device: electricity (device 0, the primary/banded device), gas (device 1) and heat
    (device 2). The unit has two modes:

      - off:  electricity [0, 0], gas [0, 0], heat [0, 0]  (no no-load fuel)
      - on:   electricity [0.4, 0.5]  and, tied by the shared operation-mode factor,
              gas  = 0.2 + 1.0 * electricity   (no-load base 0.2)
              heat = 0.1 + 0.5 * electricity   (no-load base 0.1)

    In S2 terms the "on" mode's per-commodity power_ranges are, from factor 0 (electricity
    0.4) to factor 1 (electricity 0.5): gas (0.6, 0.7) and heat (0.3, 0.35).
    """
    start = pd.Timestamp("2026-01-01T00:00+01")
    end = pd.Timestamp("2026-01-01T04:00+01")
    resolution = pd.Timedelta("PT1H")
    index = initialize_index(start=start, end=end, resolution=resolution)

    equals = pd.Series(np.nan, index=index)
    if stock_target is not None:
        equals.iloc[-1] = stock_target
    electricity = pd.DataFrame(
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
    # Gas and heat carry only a flow; their power is fully set by the operation-mode factor.
    free_commodity = pd.DataFrame(
        {
            "min": np.nan,
            "max": np.nan,
            "equals": np.nan,
            "derivative min": -10,
            "derivative max": 10,
            "derivative equals": np.nan,
        },
        index=index,
    )
    device_constraints = [electricity, free_commodity.copy(), free_commodity.copy()]
    ems_constraints = pd.DataFrame(
        {"derivative min": -100, "derivative max": 100}, index=index
    )
    energy_commitment = FlowCommitment(
        name="energy",
        index=index,
        quantity=0,
        upwards_deviation_price=pd.Series(electricity_up_price, index=index),
        downwards_deviation_price=0,
        device=pd.Series(0, index=index),
    )
    gas_commitment = FlowCommitment(
        name="gas",
        index=index,
        quantity=0,
        upwards_deviation_price=gas_up_price,
        downwards_deviation_price=0,
        device=pd.Series(1, index=index),
    )
    device_power_bands = [[(0, 0), (0.4, 0.5)], None, None]
    device_mode_commodity_ranges = [
        [{1: (0.0, 0.0), 2: (0.0, 0.0)}, {1: (0.6, 0.7), 2: (0.3, 0.35)}],
        None,
        None,
    ]
    return (
        device_constraints,
        ems_constraints,
        [energy_commitment, gas_commitment],
        device_power_bands,
        device_mode_commodity_ranges,
    )


def _run_cogen(stock_target, electricity_up_price, gas_up_price):
    (
        device_constraints,
        ems_constraints,
        commitments,
        device_power_bands,
        device_mode_commodity_ranges,
    ) = _cogeneration_setup(stock_target, electricity_up_price, gas_up_price)
    schedule, costs, results, model = device_scheduler(
        device_constraints,
        ems_constraints,
        commitments=commitments,
        device_power_bands=device_power_bands,
        device_mode_commodity_ranges=device_mode_commodity_ranges,
    )
    assert "optimal" in str(results.solver.termination_condition)
    electricity = schedule[0].values
    gas = schedule[1].values
    heat = schedule[2].values
    return electricity, gas, heat, costs


def test_cogeneration_idles_fully_when_unprofitable():
    """When running never pays off, the unit idles: every commodity is 0, no no-load fuel.

    There is no stock target, so nothing forces the unit on, and running any step costs both
    electricity (price 1) and gas (price 2 * (0.2 + electricity), incl. the no-load base).
    Idling (cost 0) therefore dominates. The unit *could* run (it has an "on" band) but must
    not spuriously do so, and in particular must not burn the no-load gas base while off.
    """
    electricity, gas, heat, costs = _run_cogen(
        stock_target=None,
        electricity_up_price=1.0,
        gas_up_price=2.0,
    )
    assert np.allclose(electricity, 0)
    assert np.allclose(gas, 0)  # no no-load fuel while off
    assert np.allclose(heat, 0)
    assert np.isclose(costs, 0.0)


def test_cogeneration_runs_at_minimum_with_affine_commodities():
    """The unit must meet a small electricity stock target, forcing minimum-level running.

    The 1.2 target cannot be met below the 0.4 mode minimum, so exactly three steps run at
    0.4 (like the single-commodity min-power-band case). Gas and heat follow the affine tie
    including their no-load bases, and the hand-computed objective is energy + gas cost:

      energy cost = 1*0.4 + 1*0.4 + 10*0.4 = 4.8   (cheap steps 1 & 3, plus one costly step)
      gas cost    = 2 * (0.6 + 0.6 + 0.6)   = 3.6   (0.6 gas per running step at 0.4)
      total       = 8.4
    """
    electricity, gas, heat, costs = _run_cogen(
        stock_target=1.2,
        electricity_up_price=[10, 1, 10, 1],
        gas_up_price=2.0,
    )
    # Three steps at the 0.4 minimum, one idle step.
    assert np.isclose(sorted(electricity), [0, 0.4, 0.4, 0.4]).all()
    assert np.isclose(electricity.sum(), 1.2)
    # Affine commodities incl. no-load base; both are zero exactly when the unit is off.
    for p, g, h in zip(electricity, gas, heat):
        if np.isclose(p, 0):
            assert np.isclose(g, 0) and np.isclose(h, 0)
        else:
            assert np.isclose(g, 0.2 + 1.0 * p)  # no-load 0.2 + proportional gas
            assert np.isclose(h, 0.1 + 0.5 * p)  # no-load 0.1 + proportional heat
    assert np.isclose(costs, 8.4)


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
