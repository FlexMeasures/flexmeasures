"""Tests for the big-M values bounding the scheduler's search space."""

from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd

from flexmeasures.data.models.planning import FlowCommitment, StockCommitment
from flexmeasures.data.models.planning.linear_optimization import device_scheduler
from flexmeasures.data.models.planning.scheduling_problem import (
    prepare_scheduling_problem,
)
from flexmeasures.data.models.planning.utils import initialize_df

#: Run every test in this module under both scheduler backends (see conftest).
RUN_UNDER_EACH_SOLVER = True

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
END = pd.Timestamp("2020-01-01T04:00:00")
RESOLUTION = timedelta(hours=1)


def make_device_constraints(power_capacity: float) -> pd.DataFrame:
    device_constraints = initialize_df(COLUMNS, START, END, RESOLUTION)
    device_constraints["derivative max"] = power_capacity
    device_constraints["derivative min"] = -power_capacity
    return device_constraints


def make_index() -> pd.DatetimeIndex:
    return initialize_df(COLUMNS, START, END, RESOLUTION).index


def test_Mc_covers_flow_limits_per_step_plus_the_committed_quantity():
    """For flow commitments, a deviation spans at most the committed quantity plus one time step's summed flow limits."""
    commitment = FlowCommitment(
        name="energy",
        quantity=-100,
        upwards_deviation_price=1,
        downwards_deviation_price=-1,
        index=make_index(),
    )
    problem = prepare_scheduling_problem(
        device_constraints=[make_device_constraints(0.5), make_device_constraints(2)],
        ems_constraints=initialize_df(COLUMNS, START, END, RESOLUTION),
        commitments=[commitment],
    )
    assert problem.Md == 2
    assert problem.Mc == 0.5 + 2 + 100


def test_Mc_covers_the_horizon_for_stock_commitments():
    """A stock commitment's deviation accumulates flows since the start, so Mc must cover the whole horizon."""
    index = make_index()
    commitment = StockCommitment(
        name="soc",
        quantity=0.5,
        upwards_deviation_price=1,
        downwards_deviation_price=-1,
        device=pd.Series(0, index=index),
        index=index,
    )
    problem = prepare_scheduling_problem(
        device_constraints=[make_device_constraints(0.5), make_device_constraints(2)],
        ems_constraints=initialize_df(COLUMNS, START, END, RESOLUTION),
        commitments=[commitment],
    )
    # 4 time steps of 0.5 + 2 flow limits each, plus the committed quantity
    assert problem.Mc == 4 * 2.5 + 0.5


def test_Mc_is_at_least_one():
    problem = prepare_scheduling_problem(
        device_constraints=[make_device_constraints(0.001)],
        ems_constraints=initialize_df(COLUMNS, START, END, RESOLUTION),
    )
    assert problem.Mc == 1


def test_large_committed_quantity_remains_feasible_under_a_non_convex_cost_curve():
    """A committed quantity far beyond the devices' flow limits must not be cut off by Mc.

    The non-convex prices (summed upwards price below summed downwards price) activate the commitment-sign constraints,
    in which Mc caps the deviations.
    Before Mc accounted for the committed quantity, the required deviation exceeded Mc and the problem was infeasible.
    """
    commitment = FlowCommitment(
        name="energy",
        quantity=-100,
        upwards_deviation_price=-1,
        downwards_deviation_price=1,
        index=make_index(),
    )
    schedule, costs, results, model = device_scheduler(
        device_constraints=[make_device_constraints(0.5)],
        ems_constraints=initialize_df(COLUMNS, START, END, RESOLUTION),
        commitments=[commitment],
    )
    assert results.solver.termination_condition == "optimal"
    # The upwards deviation earns 1 per unit, so the device consumes at full power
    np.testing.assert_allclose(schedule[0].values, 0.5, atol=1e-6)
    # Each of the 4 steps deviates upwards by 100.5 at price -1
    assert costs == -4 * 100.5
