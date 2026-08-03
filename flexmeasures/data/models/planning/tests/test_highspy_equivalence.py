"""Equivalence tests for the direct highspy scheduling backend.

Each scenario is run through ``device_scheduler`` twice: once with the Pyomo
path (``appsi_highs``) and once with the direct HiGHS path (``highspy``), and
the resulting schedules, costs and termination handling are compared.

If one of these tests fails after a change to the model in
``linear_optimization.device_scheduler``, the twin model in
``highspy_optimization.device_scheduler_highspy`` probably needs the same
change (see the note in that module's docstring).
"""

from __future__ import annotations

import inspect
from datetime import timedelta

import numpy as np
import pandas as pd
import pytest

from flexmeasures.data.models.planning import FlowCommitment, StockCommitment
from flexmeasures.data.models.planning import linear_optimization
from flexmeasures.data.models.planning.highspy_optimization import (
    device_scheduler_highspy,
)
from flexmeasures.data.models.planning.linear_optimization import device_scheduler
from flexmeasures.data.models.planning.utils import initialize_df

COLUMNS = [
    "equals",
    "max",
    "min",
    "efficiency",
    "derivative equals",
    "derivative max",
    "derivative min",
    "derivative down efficiency",
    "derivative up efficiency",
    "stock delta",
]

START = pd.Timestamp("2020-01-01T00:00:00")
END = pd.Timestamp("2020-01-02T00:00:00")
RESOLUTION = timedelta(hours=1)


def make_index():
    return initialize_df(COLUMNS, START, END, RESOLUTION).index


def make_prices(index) -> pd.Series:
    """A day of varying prices (deterministic, with a unique optimum in mind)."""
    rng = np.random.default_rng(42)
    return pd.Series(
        50
        + 40 * np.sin(np.arange(len(index)) / len(index) * 2 * np.pi)
        + rng.normal(0, 5, len(index)),
        index=index,
    )


def make_battery_constraints(
    soc_at_start: float = 0.5,
    soc_max: float = 1.0,
    soc_min: float = 0.0,
    power_capacity: float = 0.5,
    roundtrip_efficiency: float = 0.9,
    storage_efficiency: float | None = None,
) -> pd.DataFrame:
    device_constraints = initialize_df(COLUMNS, START, END, RESOLUTION)
    device_constraints["max"] = soc_max - soc_at_start
    device_constraints["min"] = soc_min - soc_at_start
    device_constraints["derivative max"] = power_capacity
    device_constraints["derivative min"] = -power_capacity
    device_constraints["derivative up efficiency"] = np.sqrt(roundtrip_efficiency)
    device_constraints["derivative down efficiency"] = 1 / np.sqrt(roundtrip_efficiency)
    if storage_efficiency is not None:
        device_constraints["efficiency"] = storage_efficiency
    return device_constraints


def make_energy_commitment(index, prices, devices=0) -> FlowCommitment:
    return FlowCommitment(
        name="energy",
        quantity=0,
        upwards_deviation_price=prices,
        downwards_deviation_price=prices,
        index=index,
        device=(
            pd.Series([devices] * len(index), index=index)
            if isinstance(devices, list)
            else pd.Series(devices, index=index)
        ),
    )


def scenario_battery_with_prices():
    """A battery trading against day-ahead prices."""
    index = make_index()
    prices = make_prices(index)
    return dict(
        device_constraints=[make_battery_constraints()],
        ems_constraints=initialize_df(COLUMNS, START, END, RESOLUTION),
        commitments=[make_energy_commitment(index, prices)],
        initial_stock=0.5,
    )


def scenario_battery_with_soc_targets():
    """A battery with a state of charge target halfway the schedule.

    Also exercises storage efficiency (losses over time) and a stock delta
    (a predefined usage profile).
    """
    index = make_index()
    prices = make_prices(index)
    device_constraints = make_battery_constraints(storage_efficiency=0.999)
    device_constraints.loc[index[12], "equals"] = 0.4  # stock target (as delta)
    device_constraints["stock delta"] = -0.01  # constant usage
    return dict(
        device_constraints=[device_constraints],
        ems_constraints=initialize_df(COLUMNS, START, END, RESOLUTION),
        commitments=[make_energy_commitment(index, prices)],
        initial_stock=0.5,
    )


def scenario_battery_with_site_capacity_and_breach_prices():
    """A battery behind a tight site capacity, with soft capacity contracts.

    Uses the same commitment structure as the StorageScheduler: an energy
    commitment, "any breach" and "all breaches" capacity commitments (both
    directions), and consumption/production peak commitments.
    """
    index = make_index()
    prices = make_prices(index)
    ems_constraints = initialize_df(COLUMNS, START, END, RESOLUTION)
    ems_constraints["derivative max"] = 0.6
    ems_constraints["derivative min"] = -0.6
    device = pd.Series(0, index=index)
    commitments = [
        make_energy_commitment(index, prices),
        FlowCommitment(
            name="any consumption breach",
            quantity=0.3,
            upwards_deviation_price=200,
            _type="any",
            index=index,
            device=device,
        ),
        FlowCommitment(
            name="all consumption breaches",
            quantity=0.3,
            upwards_deviation_price=10,
            index=index,
            device=device,
        ),
        FlowCommitment(
            name="any production breach",
            quantity=-0.3,
            downwards_deviation_price=-200,
            _type="any",
            index=index,
            device=device,
        ),
        FlowCommitment(
            name="all production breaches",
            quantity=-0.3,
            downwards_deviation_price=-10,
            index=index,
            device=device,
        ),
        FlowCommitment(
            name="consumption peak",
            quantity=0,
            upwards_deviation_price=80,
            _type="any",
            index=index,
            device=device,
        ),
        FlowCommitment(
            name="production peak",
            quantity=0,
            downwards_deviation_price=-80,
            _type="any",
            index=index,
            device=device,
        ),
    ]
    return dict(
        device_constraints=[make_battery_constraints(power_capacity=1.0)],
        ems_constraints=ems_constraints,
        commitments=commitments,
        initial_stock=0.5,
    )


def scenario_two_devices_with_stock_commitment():
    """Two batteries scheduled together, incl. a StockCommitment on one of them."""
    index = make_index()
    prices = make_prices(index)
    commitments = [
        FlowCommitment(
            name="energy",
            quantity=0,
            upwards_deviation_price=prices,
            downwards_deviation_price=prices,
            index=index,
            device=pd.Series([[0, 1]] * len(index), index=index),
            device_group=pd.Series(["site", "site"], index=[0, 1]),
        ),
        StockCommitment(
            name="prefer a full storage sooner",
            quantity=0.5,
            upwards_deviation_price=0,
            downwards_deviation_price=-0.1,
            index=index,
            device=pd.Series(0, index=index),
        ),
    ]
    return dict(
        device_constraints=[
            make_battery_constraints(),
            make_battery_constraints(power_capacity=0.3, soc_at_start=0.2),
        ],
        ems_constraints=initialize_df(COLUMNS, START, END, RESOLUTION),
        commitments=commitments,
        initial_stock=[0.5, 0.2],
    )


def scenario_infeasible():
    """A battery with an unreachable stock target (given its tiny power capacity)."""
    index = make_index()
    prices = make_prices(index)
    device_constraints = make_battery_constraints(power_capacity=0.01)
    device_constraints.loc[index[2], "equals"] = 0.4
    return dict(
        device_constraints=[device_constraints],
        ems_constraints=initialize_df(COLUMNS, START, END, RESOLUTION),
        commitments=[make_energy_commitment(index, prices)],
        initial_stock=0.5,
    )


def run_with_solver(app, solver: str, make_scenario):
    """Run a freshly built scenario with the given solver configured."""
    original_solver = app.config["FLEXMEASURES_LP_SOLVER"]
    app.config["FLEXMEASURES_LP_SOLVER"] = solver
    try:
        # Rebuild the scenario for each run, because device_scheduler mutates
        # its inputs (e.g. it adds columns to the commitment DataFrames).
        return device_scheduler(**make_scenario())
    finally:
        app.config["FLEXMEASURES_LP_SOLVER"] = original_solver


def scenario_ems_level_flow_commitment():
    """Two devices under an EMS-level flow commitment, which names no device.

    Such a commitment binds the summed flow of all devices, via
    ``ems_flow_commitment_equalities`` rather than the grouped constraints, so it
    is the case that distinguishes the two constraint families.
    """
    index = make_index()
    prices = make_prices(index)
    return dict(
        device_constraints=[make_battery_constraints(), make_battery_constraints()],
        ems_constraints=initialize_df(COLUMNS, START, END, RESOLUTION),
        commitments=[
            FlowCommitment(
                name="EMS target",
                index=index,
                quantity=0.1,
                upwards_deviation_price=prices,
                downwards_deviation_price=prices,
            )
        ],
        initial_stock=[0.5, 0.5],
    )


def scenario_ems_level_commodity_commitment():
    """An EMS-level flow commitment scoped to one commodity's devices.

    Device 0 carries the commodity, device 1 does not, so the commitment must
    bind device 0's flow only -- exercising the commodity_devices lookup rather
    than the sum-over-all-devices fallback.
    """
    index = make_index()
    prices = make_prices(index)
    commodity_commitment = FlowCommitment(
        name="gas target",
        index=index,
        quantity=0.1,
        upwards_deviation_price=prices,
        downwards_deviation_price=prices,
    )
    frame = commodity_commitment.to_frame()
    frame["commodity"] = "gas"
    # Name the commodity's device without scoping the commitment to a device
    # group, so it still routes through ems_flow_commitment_equalities.
    scoping = FlowCommitment(
        name="gas scope",
        index=index,
        quantity=0,
        upwards_deviation_price=0,
        downwards_deviation_price=0,
        device=pd.Series(0, index=index),
    ).to_frame()
    scoping["commodity"] = "gas"
    return dict(
        device_constraints=[make_battery_constraints(), make_battery_constraints()],
        ems_constraints=initialize_df(COLUMNS, START, END, RESOLUTION),
        commitments=[frame, scoping],
        initial_stock=[0.5, 0.5],
    )


@pytest.mark.parametrize(
    "make_scenario",
    [
        scenario_battery_with_prices,
        scenario_battery_with_soc_targets,
        scenario_battery_with_site_capacity_and_breach_prices,
        scenario_two_devices_with_stock_commitment,
        scenario_ems_level_flow_commitment,
        scenario_ems_level_commodity_commitment,
    ],
    ids=lambda f: f.__name__.replace("scenario_", ""),
)
def test_highspy_matches_pyomo(app, make_scenario):
    """The direct highspy backend should produce the same schedules and costs as the Pyomo backend."""
    schedule_p, costs_p, results_p, model_p = run_with_solver(
        app, "appsi_highs", make_scenario
    )
    schedule_h, costs_h, results_h, model_h = run_with_solver(
        app, "highspy", make_scenario
    )

    assert results_p.solver.termination_condition == "optimal"
    assert results_h.solver.termination_condition == "optimal"
    assert results_h.solver.status == "ok"

    # Same schedule for every device
    assert len(schedule_p) == len(schedule_h)
    for d in range(len(schedule_p)):
        assert schedule_p[d].index.equals(schedule_h[d].index)
        np.testing.assert_allclose(
            schedule_p[d].values, schedule_h[d].values, atol=1e-5
        )

    # Same total costs and same per-commitment costs
    assert costs_h == pytest.approx(costs_p, abs=1e-5)
    assert set(model_p.commitment_costs.keys()) == set(model_h.commitment_costs.keys())
    for c in model_p.commitment_costs:
        assert model_h.commitment_costs[c] == pytest.approx(
            model_p.commitment_costs[c], abs=1e-5
        )


def test_highspy_matches_pyomo_when_infeasible(app):
    """Both backends should report an infeasible problem the same way."""
    schedule_p, costs_p, results_p, _ = run_with_solver(
        app, "appsi_highs", scenario_infeasible
    )
    schedule_h, costs_h, results_h, _ = run_with_solver(
        app, "highspy", scenario_infeasible
    )

    # This is the check the StorageScheduler performs to raise an
    # InfeasibleProblemException (and to trigger its fallback scheduler).
    assert "infeasible" in results_p.solver.termination_condition
    assert "infeasible" in results_h.solver.termination_condition

    # Mirrored fallback behavior: no costs (all variables at zero)
    assert costs_p == costs_h == 0


def test_unsupported_argument_is_rejected_not_ignored():
    """A device_scheduler argument the direct backend cannot model must raise.

    ``device_scheduler`` forwards its arguments to the direct HiGHS backend by
    name. Whoever adds the next scheduling parameter (``coupling_groups`` in
    #2218, ``balance_groups`` in #2289) works on the Pyomo model, and a
    parameter that never reached the backend would not fail -- it would produce
    a schedule computed as if the constraint had never been requested. Since
    ``highspy`` is the default solver, that would be silently wrong.
    """
    real_device_scheduler = linear_optimization.device_scheduler

    def device_scheduler_of_the_future(
        device_constraints,
        ems_constraints,
        future_parameter=None,
    ):
        """Stand-in for a device_scheduler that grew a parameter."""

    linear_optimization.device_scheduler = device_scheduler_of_the_future
    try:
        arguments = dict(
            device_constraints=[], ems_constraints=None, future_parameter=None
        )

        # Left at its default, the new parameter costs existing callers nothing.
        forwarded = linear_optimization._arguments_for_highspy_backend(arguments)
        assert "future_parameter" not in forwarded
        assert set(forwarded) == {"device_constraints", "ems_constraints"}

        # Actually set, it must be reported rather than dropped.
        arguments["future_parameter"] = {"some group": [(0, 1.0)]}
        with pytest.raises(NotImplementedError, match="future_parameter"):
            linear_optimization._arguments_for_highspy_backend(arguments)
    finally:
        linear_optimization.device_scheduler = real_device_scheduler


def test_every_device_scheduler_argument_currently_reaches_the_backend():
    """The direct backend supports the whole current device_scheduler signature."""
    declared = set(inspect.signature(device_scheduler).parameters)
    supported = set(inspect.signature(device_scheduler_highspy).parameters)
    assert declared <= supported, declared - supported
