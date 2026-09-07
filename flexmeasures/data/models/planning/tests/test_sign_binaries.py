"""Tests for dropping vacuous device sign constraints (one-way devices)."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd

from flexmeasures.data.models.planning import FlowCommitment
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
END = pd.Timestamp("2020-01-01T04:00:00")
RESOLUTION = timedelta(hours=1)


def make_device_constraints(one_way: bool) -> pd.DataFrame:
    device_constraints = initialize_df(COLUMNS, START, END, RESOLUTION)
    device_constraints["derivative max"] = 0.5
    device_constraints["derivative min"] = 0 if one_way else -0.5
    return device_constraints


def test_pyomo_only_adds_sign_constraints_where_both_directions_are_available(
    app, monkeypatch
):
    """A one-way device gets no sign constraints (its sign binary goes unreferenced), a two-way device keeps them."""
    monkeypatch.setitem(app.config, "FLEXMEASURES_LP_SOLVER", "appsi_highs")
    index = initialize_df(COLUMNS, START, END, RESOLUTION).index
    commitment = FlowCommitment(
        name="energy",
        quantity=0,
        upwards_deviation_price=1,
        downwards_deviation_price=-1,
        index=index,
    )
    _, _, results, model = device_scheduler(
        device_constraints=[
            make_device_constraints(one_way=True),
            make_device_constraints(one_way=False),
        ],
        ems_constraints=initialize_df(COLUMNS, START, END, RESOLUTION),
        commitments=[commitment],
    )
    assert results.solver.termination_condition == "optimal"
    n_steps = len(index)
    # Each constraint family (up sign, down sign) is indexed over all (device, time step) pairs,
    # so with 2 devices it would hold 2 * n_steps members if every pair contributed one.
    # The one-way device contributes none: its downwards power is fixed to zero by its bounds,
    # so both of its sign constraints are vacuous and its rule returns Constraint.Skip at every time step.
    # The two-way device contributes one member per time step, leaving n_steps members per family.
    # Skipped members simply do not exist on the Pyomo model, which is what len() counts.
    assert len(model.device_power_up_sign) == n_steps
    assert len(model.device_power_down_sign) == n_steps
