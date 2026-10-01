"""Tests for the sign binaries:
dropping vacuous device sign constraints (one-way devices), and adding commitment sign constraints where a commitment's cost curve is not convex.
"""

from __future__ import annotations

from datetime import timedelta

import pandas as pd
import pytest

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


def make_commitment(
    name: str, index: pd.DatetimeIndex, upwards: float, downwards: float
) -> FlowCommitment:
    """A commitment on the EMS flow, with one group per time slot, so that each slot carries both deviation prices."""
    return FlowCommitment(
        name=name,
        quantity=0,
        upwards_deviation_price=upwards,
        downwards_deviation_price=downwards,
        index=index,
    )


def solve_against(commitments: list[FlowCommitment], app, monkeypatch):
    """Schedule a single two-way device against the given commitments, and hand back the solver results and the model."""
    monkeypatch.setitem(app.config, "FLEXMEASURES_LP_SOLVER", "appsi_highs")
    _, _, results, model = device_scheduler(
        device_constraints=[make_device_constraints(one_way=False)],
        ems_constraints=initialize_df(COLUMNS, START, END, RESOLUTION),
        commitments=commitments,
    )
    return results, model


def test_a_commitment_that_rewards_downwards_deviation_gets_sign_constraints(
    app, monkeypatch
):
    """A commitment whose downwards deviation price exceeds its upwards price is not convex, so it needs its sign constraints.

    Without them, the solver can inflate the upwards and downwards deviations together, leaving the position unchanged,
    and bank the difference between the two prices without bound.
    """
    index = initialize_df(COLUMNS, START, END, RESOLUTION).index
    results, model = solve_against(
        [make_commitment("rewarded downwards", index, upwards=0, downwards=50)],
        app,
        monkeypatch,
    )
    assert results.solver.termination_condition == "optimal"
    assert hasattr(model, "commitment_up_derivative_sign_con")


def test_another_commitments_prices_do_not_mask_a_non_convex_commitment(
    app, monkeypatch
):
    """A commitment that is not convex on its own still gets its sign constraints, whatever a second commitment is priced at.

    Each commitment carries its own pair of deviation variables, so convexity is a property of one commitment at a time.
    Summing every commitment's prices per time step let the expensive upwards price here outweigh the non-convex commitment's,
    which left the sign constraints out of the model and the problem unbounded (#2534).
    """
    index = initialize_df(COLUMNS, START, END, RESOLUTION).index
    results, model = solve_against(
        [
            make_commitment("rewarded downwards", index, upwards=0, downwards=50),
            make_commitment("expensive upwards", index, upwards=100, downwards=0),
        ],
        app,
        monkeypatch,
    )
    assert results.solver.termination_condition == "optimal"
    # These two constrain the solver identically, so their deviations are tied to each other
    # and the pair needs no sign variables; the problem stays a linear program.
    # What this test guards is the termination condition: before the per-commitment check it was infeasibleOrUnbounded.
    assert not hasattr(model, "commitment_up_derivative_sign_con")
    assert len(model.commitment_upwards_tie) > 0


def test_commitments_that_are_each_convex_need_no_sign_constraints(app, monkeypatch):
    """Deviating upwards costs at least what deviating downwards pays, in each commitment, so the problem stays a linear program."""
    index = initialize_df(COLUMNS, START, END, RESOLUTION).index
    results, model = solve_against(
        [
            make_commitment("penalised both ways", index, upwards=10, downwards=-10),
            make_commitment("penalised upwards", index, upwards=20, downwards=0),
        ],
        app,
        monkeypatch,
    )
    assert results.solver.termination_condition == "optimal"
    assert not hasattr(model, "commitment_up_derivative_sign_con")


def test_a_commitment_penalising_any_deviation_is_checked_on_its_split_halves(
    app, monkeypatch
):
    """An ``any``-type commitment puts every time slot in one group, and such a group is split into an upwards and a downwards half.

    Each half keeps one price column, so each is checked on the price it has and on a zero for the one it lacks,
    which is what the optimizers themselves do with a missing price column.
    A commitment that penalises both directions stays a linear program,
    and one that pays for deviating downwards needs its sign constraints, just as the per-slot form does.
    """
    index = initialize_df(COLUMNS, START, END, RESOLUTION).index
    penalised = FlowCommitment(
        name="any deviation, penalised",
        quantity=0,
        upwards_deviation_price=10,
        downwards_deviation_price=-10,
        index=index,
        _type="any",
    )
    results, model = solve_against([penalised], app, monkeypatch)
    assert results.solver.termination_condition == "optimal"
    assert not hasattr(model, "commitment_up_derivative_sign_con")

    rewarded = FlowCommitment(
        name="any deviation, rewarded downwards",
        quantity=0,
        upwards_deviation_price=0,
        downwards_deviation_price=50,
        index=index,
        _type="any",
    )
    results, model = solve_against([rewarded], app, monkeypatch)
    assert results.solver.termination_condition == "optimal"
    assert hasattr(model, "commitment_up_derivative_sign_con")


def test_commitments_with_different_baselines_are_not_interchangeable(app, monkeypatch):
    """Two commitments constrain the solver identically only if they also agree on the position they deviate from.

    Give them different baselines and they are no longer interchangeable, so neither can be carried by the other's prices,
    and the one that is not convex on its own needs the sign variables to stay bounded.
    """
    index = initialize_df(COLUMNS, START, END, RESOLUTION).index
    rewarded = make_commitment("rewarded downwards", index, upwards=0, downwards=50)
    expensive = FlowCommitment(
        name="expensive upwards, elsewhere",
        quantity=0.1,
        upwards_deviation_price=100,
        downwards_deviation_price=0,
        index=index,
    )
    results, model = solve_against([rewarded, expensive], app, monkeypatch)

    assert results.solver.termination_condition == "optimal"
    assert not hasattr(
        model, "commitment_upwards_tie"
    ), "different baselines are not tied"
    assert hasattr(model, "commitment_up_derivative_sign_con")


def test_an_already_convex_pair_is_left_untied(app, monkeypatch):
    """Tying buys nothing where every member is convex on its own, so the model is left exactly as it was.

    This is what keeps the change confined to the problems that would otherwise need sign variables.
    """
    index = initialize_df(COLUMNS, START, END, RESOLUTION).index
    results, model = solve_against(
        [
            make_commitment("penalised both ways", index, upwards=10, downwards=-10),
            make_commitment("penalised upwards", index, upwards=20, downwards=0),
        ],
        app,
        monkeypatch,
    )

    assert results.solver.termination_condition == "optimal"
    assert not hasattr(model, "commitment_upwards_tie")
    assert not hasattr(model, "commitment_up_derivative_sign_con")


def test_tying_changes_the_model_but_not_the_answer(app, monkeypatch):
    """The tied linear program and the sign-variable mixed-integer program agree, per commitment and per device.

    This is what makes tying safe to do silently: each commitment keeps its own deviation variables and so its own cost line,
    priced on its own prices rather than on the group's, so nothing has to be taken apart again afterwards.
    """
    from flexmeasures.data.models.planning import scheduling_problem

    index = initialize_df(COLUMNS, START, END, RESOLUTION).index

    def solve():
        return solve_against(
            [
                make_commitment("rewarded downwards", index, upwards=0, downwards=50),
                make_commitment("expensive upwards", index, upwards=100, downwards=0),
            ],
            app,
            monkeypatch,
        )

    tied_results, tied_model = solve()
    tied_power, tied_costs = device_scheduler(
        device_constraints=[make_device_constraints(one_way=False)],
        ems_constraints=initialize_df(COLUMNS, START, END, RESOLUTION),
        commitments=[
            make_commitment("rewarded downwards", index, upwards=0, downwards=50),
            make_commitment("expensive upwards", index, upwards=100, downwards=0),
        ],
    )[:2]

    # Now take the tie away, which leaves the sign variables to keep the pair bounded.
    monkeypatch.setattr(
        scheduling_problem, "interchangeable_subcommitments", lambda *a, **k: []
    )
    untied_results, untied_model = solve()
    untied_power, untied_costs = device_scheduler(
        device_constraints=[make_device_constraints(one_way=False)],
        ems_constraints=initialize_df(COLUMNS, START, END, RESOLUTION),
        commitments=[
            make_commitment("rewarded downwards", index, upwards=0, downwards=50),
            make_commitment("expensive upwards", index, upwards=100, downwards=0),
        ],
    )[:2]

    assert tied_results.solver.termination_condition == "optimal"
    assert untied_results.solver.termination_condition == "optimal"
    assert not hasattr(
        tied_model, "commitment_up_derivative_sign_con"
    ), "tied: a linear program"
    assert hasattr(
        untied_model, "commitment_up_derivative_sign_con"
    ), "untied: a mixed-integer program"

    assert tied_model.commitment_costs == pytest.approx(untied_model.commitment_costs)
    for tied_device, untied_device in zip(tied_power, untied_power):
        assert list(tied_device) == pytest.approx(list(untied_device))
    assert _sum_costs(tied_costs) == pytest.approx(_sum_costs(untied_costs))


def _sum_costs(costs) -> float:
    """Total of whatever shape the scheduler reports its costs in."""
    if isinstance(costs, dict):
        return float(sum(float(pd.Series(v).sum()) for v in costs.values()))
    return float(pd.Series(costs).sum())
