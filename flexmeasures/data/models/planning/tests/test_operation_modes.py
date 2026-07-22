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


def _cogeneration_modes():
    """The two operation modes of an affine cogeneration unit, sign-explicit (S2 shape).

    The unit produces electricity (its own, banded flow) and heat, while consuming gas:

      - off:  everything 0 (no no-load fuel)
      - on:   electricity produced in [0.4, 0.5] MW and, tied by the shared operation-mode
              factor, gas = 0.2 + 1.0 * |electricity| (consumed; no-load base 0.2) and
              heat = 0.1 + 0.5 * |electricity| (produced; no-load base 0.1).

    Electricity and heat therefore use ``production-range`` and gas uses ``consumption-range``.
    Loaded through ``OperationModeSchema`` and reduced to signed scheduler bands via the shared
    ``_operation_mode_signed_band`` / ``_operation_mode_commodity_bands`` helpers.
    """
    return [
        {
            "production-range": ["0 MW", "0 MW"],
            "commodity-power-ranges": [
                {"commodity": "gas", "consumption-range": ["0 MW", "0 MW"]},
                {"commodity": "heat", "production-range": ["0 MW", "0 MW"]},
            ],
        },
        {
            # electricity produced between 0.4 and 0.5 MW when on
            "production-range": ["0.4 MW", "0.5 MW"],
            "commodity-power-ranges": [
                # gas consumed: 0.6 at 0.4 output, 0.7 at 0.5 output (base 0.2, slope 1.0)
                {"commodity": "gas", "consumption-range": ["0.6 MW", "0.7 MW"]},
                # heat produced: 0.3 at 0.4 output, 0.35 at 0.5 output (base 0.1, slope 0.5)
                {"commodity": "heat", "production-range": ["0.3 MW", "0.35 MW"]},
            ],
        },
    ]


def _cogeneration_setup(
    delivery_target: float | None,
    electricity_price,
    gas_price: float,
):
    """A unit-committed affine cogeneration unit as a multi-commodity operation mode.

    Three scheduler devices share one operation-mode binary carried by the (banded)
    electricity device: electricity (device 0, the primary/banded device, producing so its
    signed power is non-positive), gas (device 1, consumed) and heat (device 2, produced).
    The sign-explicit modes are turned into signed scheduler bands via the storage helpers,
    exactly as ``StorageScheduler`` would.
    """
    from flexmeasures.data.schemas.scheduling.storage import OperationModeSchema
    from flexmeasures.data.models.planning.storage import (
        _operation_mode_signed_band,
        _operation_mode_commodity_bands,
    )

    start = pd.Timestamp("2026-01-01T00:00+01")
    end = pd.Timestamp("2026-01-01T04:00+01")
    resolution = pd.Timedelta("PT1H")
    index = initialize_index(start=start, end=end, resolution=resolution)

    modes = [OperationModeSchema().load(mode) for mode in _cogeneration_modes()]
    # Primary (electricity) signed bands and per-commodity (gas=1, heat=2) signed endpoints.
    device_power_bands = [
        [_operation_mode_signed_band(mode) for mode in modes],
        None,
        None,
    ]
    commodity_index = {"gas": 1, "heat": 2}
    device_mode_commodity_ranges = [
        [
            {
                commodity_index[name]: band
                for name, band in _operation_mode_commodity_bands(mode).items()
            }
            for mode in modes
        ],
        None,
        None,
    ]

    equals = pd.Series(np.nan, index=index)
    if delivery_target is not None:
        # Negative stock target: the unit must net-produce ``delivery_target`` MWh.
        equals.iloc[-1] = -delivery_target
    electricity = pd.DataFrame(
        {
            "min": -10,
            "max": 10,
            "equals": equals,
            "derivative min": -0.5,  # production only
            "derivative max": 0,
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
    # Producing electricity earns revenue: a positive price on the deviation from a zero
    # quantity makes the (negative) electricity flow lower the objective. Pricing both
    # directions equally keeps the commitment convex and pins the deviation to the flow
    # (the electricity device is production-only, so only the downward side is ever active).
    energy_commitment = FlowCommitment(
        name="energy",
        index=index,
        quantity=0,
        upwards_deviation_price=pd.Series(electricity_price, index=index),
        downwards_deviation_price=pd.Series(electricity_price, index=index),
        device=pd.Series(0, index=index),
    )
    # Consuming gas costs money: a positive price on the upward (consumption) deviation.
    gas_commitment = FlowCommitment(
        name="gas",
        index=index,
        quantity=0,
        upwards_deviation_price=gas_price,
        downwards_deviation_price=0,
        device=pd.Series(1, index=index),
    )
    return (
        device_constraints,
        ems_constraints,
        [energy_commitment, gas_commitment],
        device_power_bands,
        device_mode_commodity_ranges,
    )


def _run_cogen(delivery_target, electricity_price, gas_price):
    (
        device_constraints,
        ems_constraints,
        commitments,
        device_power_bands,
        device_mode_commodity_ranges,
    ) = _cogeneration_setup(delivery_target, electricity_price, gas_price)
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

    There is no delivery target, so nothing forces the unit on. Running a step earns only
    0.4 * 1 in electricity revenue but burns gas worth 2 * (0.2 + 0.4) = 1.2, a net cost of
    0.8. Idling (cost 0) therefore dominates. The unit *could* run (it has an "on" band) but
    must not spuriously do so, and in particular must not burn the no-load gas base while off.
    """
    electricity, gas, heat, costs = _run_cogen(
        delivery_target=None,
        electricity_price=1.0,
        gas_price=2.0,
    )
    assert np.allclose(electricity, 0)
    assert np.allclose(gas, 0)  # no no-load fuel while off
    assert np.allclose(heat, 0)
    assert np.isclose(costs, 0.0)


def test_cogeneration_runs_at_minimum_with_affine_commodities():
    """The unit must deliver a small amount of electricity, forcing minimum-level running.

    A 1.2 MWh net-production target cannot be met below the 0.4 MW mode minimum, so exactly
    three steps run at 0.4 MW output. Gas (consumed) and heat (produced) follow the affine
    tie including their no-load bases, and the hand-computed objective is revenue + gas cost.
    Revenue is maximised by producing in the three highest-priced steps (prices [10, 1, 10, 1],
    so both 10-steps and one 1-step):

      revenue  = -(0.4*10 + 0.4*10 + 0.4*1) = -8.4   (negative == earned)
      gas cost =   2 * (0.6 + 0.6 + 0.6)    =  3.6   (0.6 gas consumed per step at 0.4)
      total    = -4.8
    """
    electricity, gas, heat, costs = _run_cogen(
        delivery_target=1.2,
        electricity_price=[10, 1, 10, 1],
        gas_price=2.0,
    )
    # Three steps producing at the 0.4 MW minimum (negative == production), one idle step.
    assert np.isclose(sorted(electricity), [-0.4, -0.4, -0.4, 0]).all()
    assert np.isclose(electricity.sum(), -1.2)
    # Both high-priced steps (0 and 2) are used.
    assert np.isclose(electricity[0], -0.4) and np.isclose(electricity[2], -0.4)
    # Affine commodities incl. no-load base; both are zero exactly when the unit is off.
    for p, g, h in zip(electricity, gas, heat):
        output = -p  # electricity produced (>= 0)
        if np.isclose(output, 0):
            assert np.isclose(g, 0) and np.isclose(h, 0)
        else:
            assert np.isclose(g, 0.2 + 1.0 * output)  # gas consumed (positive)
            assert np.isclose(h, -(0.1 + 0.5 * output))  # heat produced (negative)
    assert np.isclose(costs, -4.8)


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


# --- schema: consumption-range / production-range -> signed band -----------------

import pytest  # noqa: E402
from marshmallow import ValidationError  # noqa: E402

from flexmeasures.data.schemas.scheduling.storage import (  # noqa: E402
    OperationModeSchema,
)
from flexmeasures.data.models.planning.storage import (  # noqa: E402
    _operation_mode_signed_band,
)


def _band(payload):
    return _operation_mode_signed_band(OperationModeSchema().load(payload))


def test_consumption_range_maps_to_positive_band():
    # The S2 signed power-range maps to the FM consumption-range.
    assert _band({"consumption-range": ["0 MW", "10 MW"]}) == (0.0, 10.0)


def test_production_range_maps_to_negative_band():
    assert _band({"production-range": ["4 MW", "55 MW"]}) == (-55.0, -4.0)


def test_combined_ranges_form_a_band_through_zero():
    assert _band(
        {"consumption-range": ["0 MW", "20 MW"], "production-range": ["0 MW", "55 MW"]}
    ) == (-55.0, 20.0)


def test_operation_mode_requires_at_least_one_range():
    with pytest.raises(ValidationError):
        OperationModeSchema().load({})


def test_combined_ranges_must_start_at_zero():
    with pytest.raises(ValidationError, match="contiguous band"):
        OperationModeSchema().load(
            {
                "consumption-range": ["1 MW", "20 MW"],
                "production-range": ["0 MW", "55 MW"],
            }
        )


def test_range_min_cannot_exceed_max():
    with pytest.raises(ValidationError):
        OperationModeSchema().load({"consumption-range": ["10 MW", "5 MW"]})
