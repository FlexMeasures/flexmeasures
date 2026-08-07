from __future__ import annotations

import inspect
from functools import lru_cache

from flask import current_app
import pandas as pd
import numpy as np
from pyomo.core import (
    ConcreteModel,
    Var,
    RangeSet,
    Set,
    Param,
    Reals,
    NonNegativeReals,
    NonPositiveReals,
    Binary,
    Constraint,
    Objective,
    minimize,
)
from pyomo.environ import UnknownSolver  # noqa F401
from pyomo.environ import value
from pyomo.opt import SolverFactory, SolverResults

from flexmeasures.data.models.planning import (
    Commitment,
    FlowCommitment,
    StockCommitment,
)
from flexmeasures.data.models.planning.scheduling_problem import (  # noqa F401
    aggregate_commodity_costs,
    aggregate_subcommitment_costs,
    convert_commitments_to_subcommitments,
    loss_coefficients,
    planned_power_per_device,
    prepare_scheduling_problem,
    solver_options,
    validate_highs_options,
)

infinity = float("inf")


def _left_at_default(value, default) -> bool:
    """Whether an argument was left at its default.

    Best-effort: pandas values compare element-wise, so ``value == default`` may return an array (or raise) rather than a bool.
    Anything we cannot decide is reported as "not the default",
    which errs towards raising in :func:`_arguments_for_highspy_backend` rather than silently dropping a value.
    """
    if value is default:
        return True
    if default is inspect.Parameter.empty:
        return False
    try:
        return bool(value == default)
    except (TypeError, ValueError):
        return False


@lru_cache(maxsize=None)
def _backend_argument_map(declared_by, supported_by) -> tuple[frozenset, tuple]:
    """Which of ``declared_by``'s arguments ``supported_by`` accepts, and which it lacks.

    Signatures are static, so this is computed once per process (roughly 70 us, which is not worth paying on every schedule).
    Caching on the two function objects rather than on nothing keeps it correct when a test substitutes one of them.
    """
    declared = inspect.signature(declared_by).parameters
    supported = frozenset(inspect.signature(supported_by).parameters)
    missing = tuple(
        (name, parameter.default)
        for name, parameter in declared.items()
        if name not in supported
    )
    return frozenset(declared) & supported, missing


def _arguments_for_highspy_backend(passed_arguments: dict) -> dict:
    """Map ``device_scheduler``'s arguments onto the direct HiGHS backend's signature.

    A hand-written keyword list here would be a trap:
    whoever adds the next ``device_scheduler`` parameter naturally works on the Pyomo model further down this file,
    and a parameter missing from that list would not fail — it would simply never reach the backend.
    Under ``FLEXMEASURES_LP_SOLVER="highspy"`` (the default),
    that yields a schedule computed as if the constraint had never been requested:
    plausible-looking, silently wrong, and not caught by tests written before the default was flipped.

    Forwarding by name removes that failure mode entirely.
    The remaining case — an argument the direct backend does not model at all —
    is caught statically by ``test_every_device_scheduler_argument_currently_reaches_the_backend``, so it cannot reach a release.
    The raise below is only a backstop for a build where that test did not run;
    it costs nothing while the signatures agree.

    This is a live concern rather than a hypothetical one:
    ``device_scheduler`` is gaining ``coupling_groups`` (#2218) and ``balance_groups`` (#2289) on branches in flight,
    and each needs explicit support here.
    """
    from flexmeasures.data.models.planning.highspy_optimization import (
        device_scheduler_highspy,
    )

    forwardable, missing = _backend_argument_map(
        device_scheduler, device_scheduler_highspy
    )
    if missing:
        in_use = sorted(
            name
            for name, default in missing
            if not _left_at_default(passed_arguments[name], default)
        )
        if in_use:
            raise NotImplementedError(
                "The direct HiGHS backend (FLEXMEASURES_LP_SOLVER='highspy') does not"
                f" model these device_scheduler arguments: {', '.join(in_use)}."
                " Add support for them in"
                " flexmeasures.data.models.planning.highspy_optimization (and extend"
                " tests/test_highspy_equivalence.py), or configure a Pyomo-based"
                " solver such as 'appsi_highs'."
            )
    return {
        name: value for name, value in passed_arguments.items() if name in forwardable
    }


def device_scheduler(  # noqa C901
    device_constraints: list[pd.DataFrame],
    ems_constraints: pd.DataFrame | list[pd.DataFrame],
    commitment_quantities: list[pd.Series] | None = None,
    commitment_downwards_deviation_price: list[pd.Series] | list[float] | None = None,
    commitment_upwards_deviation_price: list[pd.Series] | list[float] | None = None,
    commitments: list[pd.DataFrame] | list[Commitment] | None = None,
    initial_stock: float | list[float] = 0,
    stock_groups: dict[int, list[int]] | None = None,
    coupling_groups: dict[str, list[tuple[int, float]]] | None = None,
    balance_groups: dict[str, list[int]] | None = None,
    ems_constraint_groups: list[list[int]] | None = None,
    device_power_bands: list[list[tuple[float, float]] | None] | None = None,
) -> tuple[list[pd.Series], float, SolverResults, ConcreteModel]:
    """This generic device scheduler is able to handle an EMS with multiple devices,
    with various types of constraints on the EMS level and on the device level,
    and with multiple market commitments on the EMS level.
    A typical example is a house with many devices.
    The commitments are assumed to be with regard to the flow of energy to the device (positive for consumption,
    negative for production). The solver minimises the costs of deviating from the commitments.

    :param device_constraints:  Device constraints are on a device level. Handled constraints (listed by column name):
                                    max: maximum stock assuming an initial stock of zero (e.g. in MWh or boxes)
                                    min: minimum stock assuming an initial stock of zero
                                    equal: exact amount of stock (we do this by clamping min and max)
                                    efficiency: amount of stock left at the next datetime (the rest is lost)
                                    derivative max: maximum flow (e.g. in MW or boxes/h)
                                    derivative min: minimum flow
                                    derivative equals: exact amount of flow (we do this by clamping derivative min and derivative max)
                                    derivative down efficiency: conversion efficiency of flow out of a device (flow out : stock decrease)
                                    derivative up efficiency: conversion efficiency of flow into a device (stock increase : flow in)
                                    stock delta: predefined stock delta to apply to the storage device. Positive values cause an increase and negative values a decrease
    :param ems_constraints:     EMS constraints are on an EMS level. Handled constraints (listed by column name):
                                    derivative max: maximum flow
                                    derivative min: minimum flow
                                May be a single DataFrame (the constraint is applied to the summed flow of all devices),
                                or a list of DataFrames (one per device group). In the latter case, ``ems_constraint_groups``
                                lists the device indices each DataFrame applies to. The StorageScheduler uses one device
                                group per commodity, so each commodity gets its own EMS-level capacity constraint.
    :param ems_constraint_groups: For each EMS constraint DataFrame, the list of device indices it applies to. When omitted,
                                each EMS constraint is applied to the summed flow of all devices (legacy behaviour). A device
                                may appear in more than one group.
    :param commitments:         Commitments are on an EMS level by default. Handled parameters (listed by column name):
                                    quantity:                   for example, 5.5
                                    downwards deviation price:  10.1
                                    upwards deviation price:    10.2
                                    group:                      1 (defaults to the enumerate time step j)
                                    device:                     0 (corresponds to device d; if not set, commitment is on an EMS level)
    :param initial_stock:       initial stock for each device. Use a list with the same number of devices as device_constraints,
                                or use a single value to set the initial stock to be the same for all devices.
    :param coupling_groups:     Hard flow-coupling constraints between devices. Each entry maps a group name to a list of
                                ``(device_index, coefficient)`` tuples. A decision variable ``alpha`` is introduced per group
                                per time step and every device ``d`` in the group is constrained by ``P[d, j] == coeff_d * alpha[group, j]``.
                                Sign convention: positive coefficient for input devices (consuming, positive ``ems_power``),
                                negative coefficient for output devices (producing, negative ``ems_power``).
                                Example — a CHP with gas input (d=0, coeff 1.0), heat output (d=1, coeff −0.5) and
                                power output (d=2, coeff −0.3)::

                                    coupling_groups={"chp": [(0, 1.0), (1, -0.5), (2, -0.3)]}
    :param device_power_bands:  optional per-device list of signed power bands (min, max), in flow units
                                (e.g. MW, positive for consumption). A device with bands must operate within
                                one of its bands at every time step (see S2 operation modes); this introduces
                                binary variables (one per device per band per time step). Use None (per device
                                or for the whole argument) for devices without band restrictions.

    :param balance_groups:      Flow-balance constraints for internal commodity nodes (e.g. a heat or steam network without a grid connection).
                                Each entry maps a node name to a list of device indices whose commodity-side flows must balance at every time step:
                                ``sum_d(ems_power[d, j]) == 0``.
                                In other words, everything produced into the node is consumed from it within the same time step;
                                the node itself stores nothing.
                                Derivative efficiencies and stock deltas describe each device's own stock-side conversion,
                                and do not enter this commodity-side balance.
                                To add storage to a node, include a storage device in the group:
                                its flow absorbs the imbalance, and its stock is bounded by its own device constraints.

    Potentially deprecated arguments:
        commitment_quantities: amounts of flow specified in commitments (both previously ordered and newly requested)
            - e.g. in MW or boxes/h
        commitment_downwards_deviation_price: penalty for downwards deviations of the flow
            - e.g. in EUR/MW or EUR/(boxes/h)
            - either a single value (same value for each flow value) or a Series (different value for each flow value)
        commitment_upwards_deviation_price: penalty for upwards deviations of the flow

    Separate costs for each commitment are stored in a dictionary under `model.commitment_costs` (indexed by commitment).

    All Series and DataFrames should have the same resolution.

    For now, we pass in the various constraints and prices as separate variables, from which we make a MultiIndex
    DataFrame. Later we could pass in a MultiIndex DataFrame directly.
    """

    # The "highspy" solver choice bypasses Pyomo altogether:
    # the same model is built directly with the HiGHS Python API (much faster to construct).
    # See the highspy_optimization module, which mirrors the model built below and returns compatible result objects.
    if current_app.config.get("FLEXMEASURES_LP_SOLVER") == "highspy":
        # Arguments are forwarded by name,
        # and an argument the direct backend cannot model raises rather than being dropped.
        # See _arguments_for_highspy_backend.
        highspy_arguments = _arguments_for_highspy_backend(locals())

        from flexmeasures.data.models.planning.highspy_optimization import (
            device_scheduler_highspy,
        )

        return device_scheduler_highspy(**highspy_arguments)

    model = ConcreteModel()

    # If the EMS has no devices, don't bother
    if len(device_constraints) == 0:
        return [], 0, SolverResults(), model

    problem = prepare_scheduling_problem(
        device_constraints=device_constraints,
        ems_constraints=ems_constraints,
        commitment_quantities=commitment_quantities,
        commitment_downwards_deviation_price=commitment_downwards_deviation_price,
        commitment_upwards_deviation_price=commitment_upwards_deviation_price,
        commitments=commitments,
        initial_stock=initial_stock,
        stock_groups=stock_groups,
        ems_constraint_groups=ems_constraint_groups,
        device_power_bands=device_power_bands,
        coupling_groups=coupling_groups,
        balance_groups=balance_groups,
    )

    # Local aliases,
    # so that the model below reads as it did before the (solver-agnostic) input handling moved to the scheduling_problem module.
    start, end, resolution = problem.start, problem.end, problem.resolution
    device_constraints = problem.device_constraints
    ems_constraints_list = problem.ems_constraints_list
    ems_constraint_device_groups = problem.ems_constraint_device_groups
    device_to_group = problem.device_to_group
    group_to_devices = problem.group_to_devices
    commitments = problem.commitments
    commitment_mapping = problem.commitment_mapping
    device_group_lookup = problem.device_group_lookup
    convex_cost_curve = problem.convex_cost_curve
    Md, Mc = problem.Md, problem.Mc
    band_lookup = problem.band_lookup
    _initial_stock_of = problem.initial_stock_of
    coupling_device_specs = problem.coupling_device_specs
    balance_group_specs = problem.balance_group_specs

    # Add indices for devices (d), datetimes (j) and commitments (c)
    model.d = RangeSet(0, len(device_constraints) - 1, doc="Set of devices")
    model.j = RangeSet(
        0, len(device_constraints[0].index.to_pydatetime()) - 1, doc="Set of datetimes"
    )
    model.c = RangeSet(0, len(commitments) - 1, doc="Set of commitments")

    # Add 2D indices for commitment device groups (cg)
    def commitment_device_groups_init(m):
        return ((c, g) for c, groups in device_group_lookup.items() for g in groups)

    model.cg = Set(dimen=2, initialize=commitment_device_groups_init)

    # Add 2D indices for commitment datetimes (cj)
    def commitments_init(m):
        return ((c, j) for c in m.c for j in commitments[c]["j"])

    model.cj = Set(dimen=2, initialize=commitments_init)

    # Add 3D indices for commitment datetime device groups (cjg)
    def commitment_time_device_groups_init(m):
        return ((c, j, g) for (c, j) in m.cj for (_, g) in m.cg if _ == c)

    model.cjg = Set(dimen=3, initialize=commitment_time_device_groups_init)

    # Add parameters
    def price_down_select(m, c):
        if "downwards deviation price" not in commitments[c].columns:
            return 0
        price = commitments[c]["downwards deviation price"].iloc[0]
        if np.isnan(price):
            return 0
        return price

    def price_up_select(m, c):
        if "upwards deviation price" not in commitments[c].columns:
            return 0
        price = commitments[c]["upwards deviation price"].iloc[0]
        if np.isnan(price):
            return 0
        return price

    def commitment_quantity_select(m, c, j):
        quantity = commitments[c][commitments[c]["j"] == j]["quantity"].values[0]
        if np.isnan(quantity):
            return -infinity
        return quantity

    def device_max_select(m, d, j):
        min_v = device_constraints[d]["min"].iloc[j]
        max_v = device_constraints[d]["max"].iloc[j]
        equal_v = device_constraints[d]["equals"].iloc[j]
        if np.isnan(max_v) and np.isnan(equal_v):
            return infinity
        else:
            if not np.isnan(equal_v):
                # make min_v < equal_v
                equal_v = np.nanmax([equal_v, min_v])

            return np.nanmin([max_v, equal_v])

    def device_min_select(m, d, j):
        min_v = device_constraints[d]["min"].iloc[j]
        max_v = device_constraints[d]["max"].iloc[j]
        equal_v = device_constraints[d]["equals"].iloc[j]
        if np.isnan(min_v) and np.isnan(equal_v):
            return -infinity
        else:
            if not np.isnan(equal_v):
                # make equal_v <= max_v
                equal_v = np.nanmin([equal_v, max_v])

            return np.nanmax([min_v, equal_v])

    def device_derivative_max_select(m, d, j):
        max_v = device_constraints[d]["derivative max"].iloc[j]
        equal_v = device_constraints[d]["derivative equals"].iloc[j]
        if np.isnan(max_v) and np.isnan(equal_v):
            return infinity
        else:
            return np.nanmin([max_v, equal_v])

    def device_derivative_min_select(m, d, j):
        min_v = device_constraints[d]["derivative min"].iloc[j]
        equal_v = device_constraints[d]["derivative equals"].iloc[j]
        if np.isnan(min_v) and np.isnan(equal_v):
            return -infinity
        else:
            return np.nanmax([min_v, equal_v])

    def ems_derivative_max_select(m, g, j):
        v = ems_constraints_list[g]["derivative max"].iloc[j]
        if np.isnan(v):
            return infinity
        else:
            return v

    def ems_derivative_min_select(m, g, j):
        v = ems_constraints_list[g]["derivative min"].iloc[j]
        if np.isnan(v):
            return -infinity
        else:
            return v

    def device_efficiency(m, d, j):
        """Assume perfect efficiency if no efficiency information is available."""
        try:
            eff = device_constraints[d]["efficiency"].iloc[j]
        except KeyError:
            return 1
        if np.isnan(eff):
            return 1
        return eff

    def device_derivative_down_efficiency(m, d, j):
        """Assume perfect efficiency if no efficiency information is available."""
        try:
            eff = device_constraints[d]["derivative down efficiency"].iloc[j]
        except KeyError:
            return 1
        if np.isnan(eff):
            return 1
        return eff

    def device_derivative_up_efficiency(m, d, j):
        """Assume perfect efficiency if no efficiency information is available."""
        try:
            eff = device_constraints[d]["derivative up efficiency"].iloc[j]
        except KeyError:
            return 1
        if np.isnan(eff):
            return 1
        return eff

    def device_stock_delta(m, d, j):
        return device_constraints[d]["stock delta"].iloc[j]

    def grouped_commitment_equalities(m, c, j, g):
        """
        Enforce a commitment deviation constraint on the aggregate of devices in a group.

        For commitment ``c`` at time index ``j``, this constraint couples the commitment
        baseline (plus deviation variables) to the summed flow or stock of all devices
        belonging to device group ``g``. StockCommitments aggregate device stocks, while
        FlowCommitments aggregate device flows. Constraints are skipped if the commitment
        is inactive at ``(c, j)`` or if the group contains no devices.
        """
        if m.commitment_quantity[c, j] == -infinity:
            return Constraint.Skip

        devices_in_group = device_group_lookup.get(c, {}).get(g, set())
        if not devices_in_group:
            return Constraint.Skip

        center = (
            m.commitment_quantity[c, j]
            + m.commitment_downwards_deviation[c]
            + m.commitment_upwards_deviation[c]
        )

        if commitments[c]["class"].apply(lambda cl: cl == StockCommitment).all():
            center -= sum(_get_stock_change(m, d, j) for d in devices_in_group)
        else:
            center -= sum(m.ems_power[d, j] for d in devices_in_group)

        return (
            0 if "upwards deviation price" in commitments[c].columns else None,
            center,
            0 if "downwards deviation price" in commitments[c].columns else None,
        )

    model.up_price = Param(model.c, initialize=price_up_select)
    model.down_price = Param(model.c, initialize=price_down_select)
    model.commitment_quantity = Param(
        model.cj, domain=Reals, initialize=commitment_quantity_select
    )
    model.device_max = Param(model.d, model.j, initialize=device_max_select)
    model.device_min = Param(model.d, model.j, initialize=device_min_select)
    model.device_derivative_max = Param(
        model.d, model.j, initialize=device_derivative_max_select
    )
    model.device_derivative_min = Param(
        model.d, model.j, initialize=device_derivative_min_select
    )
    model.eg = RangeSet(
        0, len(ems_constraints_list) - 1, doc="Set of EMS constraint (device) groups"
    )
    model.ems_derivative_max = Param(
        model.eg, model.j, initialize=ems_derivative_max_select
    )
    model.ems_derivative_min = Param(
        model.eg, model.j, initialize=ems_derivative_min_select
    )
    model.device_efficiency = Param(model.d, model.j, initialize=device_efficiency)
    model.device_derivative_down_efficiency = Param(
        model.d, model.j, initialize=device_derivative_down_efficiency
    )
    model.device_derivative_up_efficiency = Param(
        model.d, model.j, initialize=device_derivative_up_efficiency
    )
    model.stock_delta = Param(model.d, model.j, initialize=device_stock_delta)

    # Add variables
    model.ems_power = Var(model.d, model.j, domain=Reals, initialize=0)
    model.device_power_down = Var(
        model.d, model.j, domain=NonPositiveReals, initialize=0
    )
    model.device_power_up = Var(model.d, model.j, domain=NonNegativeReals, initialize=0)
    model.device_power_sign = Var(model.d, model.j, domain=Binary, initialize=0)
    # Stock per stock group per time step, coupled recursively by group_stock_balance.
    # Having it as a variable (rather than a running sum expression) keeps the number
    # of model nonzeros linear, rather than quadratic, in the scheduling horizon, and
    # indexing it by stock group (rather than by device) avoids duplicating the
    # recursion for each device sharing a stock.
    model.sg = Set(initialize=sorted(group_to_devices), doc="Set of stock groups")
    model.group_stock = Var(model.sg, model.j, domain=Reals, initialize=0)
    model.commitment_downwards_deviation = Var(
        model.c,
        domain=NonPositiveReals,
        initialize=0,
        # bounds=[-1000, None],  # useful for debugging, to distinguish between infeasible and unbounded problems
    )
    model.commitment_upwards_deviation = Var(
        model.c,
        domain=NonNegativeReals,
        initialize=0,
        # bounds=[None, 1000],
    )
    model.commitment_sign = Var(model.c, domain=Binary, initialize=0)

    def _stock_change_at(m, g, j):
        """Stock change of stock group g during time step j (before losses)."""
        return sum(
            m.device_power_down[dev, j] / m.device_derivative_down_efficiency[dev, j]
            + m.device_power_up[dev, j] * m.device_derivative_up_efficiency[dev, j]
            + m.stock_delta[dev, j]
            for dev in group_to_devices[g]
        )

    def group_stock_balance(m, g, j):
        """Recursively couple a stock group's stock to the previous step's stock.

        Expressing stock[j] as a running sum over all k <= j (as this once did) makes
        the number of nonzeros grow quadratically with the scheduling horizon. The
        recursion below is equivalent and keeps it linear.

        The group's devices share their storage efficiency and initial stock
        (validated above), so the first device can represent the group here.
        """
        d0 = group_to_devices[g][0]
        a, b = loss_coefficients(m.device_efficiency[d0, j])
        previous = m.group_stock[g, j - 1] if j > 0 else _initial_stock_of(d0)
        return m.group_stock[g, j] == a * previous + b * _stock_change_at(m, g, j)

    def _get_stock_change(m, d, j):
        """Stock change of the stock group of device d, from the start until time j."""
        return m.group_stock[device_to_group[d], j] - _initial_stock_of(d)

    # Add constraints as a tuple of (lower bound, value, upper bound)
    def device_bounds(m, d, j):
        """Constraints on the device's stock."""
        return (
            m.device_min[d, j],
            _get_stock_change(m, d, j),
            m.device_max[d, j],
        )

    def device_derivative_bounds(m, d, j):
        return (
            m.device_derivative_min[d, j],
            m.device_power_down[d, j] + m.device_power_up[d, j],
            m.device_derivative_max[d, j],
        )

    def device_down_derivative_bounds(m, d, j):
        """Strictly non-positive."""
        return (
            min(m.device_derivative_min[d, j], 0),
            m.device_power_down[d, j],
            0,
        )

    def device_up_derivative_bounds(m, d, j):
        """Strictly non-negative."""
        return (
            0,
            m.device_power_up[d, j],
            max(0, m.device_derivative_max[d, j]),
        )

    def _sign_constraint_is_vacuous(m, d, j):
        """Whether the sign constraints cannot bind: one power direction is fixed to zero by its bounds,
        so upwards and downwards activation cannot be simultaneous anyway.
        Skipping them leaves the sign binary unreferenced (a one-way device needs no binary at all).
        """
        return m.device_derivative_min[d, j] >= 0 or m.device_derivative_max[d, j] <= 0

    def device_up_derivative_sign(m, d, j):
        """Derivative up if sign points up, derivative not up if sign points down."""
        if _sign_constraint_is_vacuous(m, d, j):
            return Constraint.Skip
        return m.device_power_up[d, j] <= Md * m.device_power_sign[d, j]

    def device_down_derivative_sign(m, d, j):
        """Derivative down if sign points down, derivative not down if sign points up."""
        if _sign_constraint_is_vacuous(m, d, j):
            return Constraint.Skip
        return -m.device_power_down[d, j] <= Md * (1 - m.device_power_sign[d, j])

    def ems_derivative_bounds(m, g, j):
        devices = ems_constraint_device_groups[g]
        if not devices:
            return Constraint.Skip
        return (
            m.ems_derivative_min[g, j],
            sum(m.ems_power[d, j] for d in devices),
            m.ems_derivative_max[g, j],
        )

    def commitment_up_derivative_sign(m, c):
        """Up deviation active only if sign points up."""
        return m.commitment_upwards_deviation[c] <= Mc * m.commitment_sign[c]

    def commitment_down_derivative_sign(m, c):
        """Down deviation active only if sign points down."""
        return -m.commitment_downwards_deviation[c] <= Mc * (1 - m.commitment_sign[c])

    def ems_flow_commitment_equalities(m, c, j):
        """Couple EMS flow commitments to device flows, optionally filtered by commodity."""

        if commitments[c]["class"].iloc[0] != FlowCommitment:
            return Constraint.Skip

        # A device-scoped commitment is already bound, once per device group, by grouped_commitment_equalities.
        # Now that this constraint family actually has bounds,
        # binding such a commitment here as well would constrain the same deviation variables a second time,
        # against a different device set (the whole EMS, or the whole commodity).
        # Only genuinely EMS-level commitments -- those naming no device -- belong here.
        if device_group_lookup.get(c):
            return Constraint.Skip

        # Legacy behavior: no commodity → sum over all devices
        if "commodity" not in commitments[c].columns:
            devices = m.d
        else:
            commodity = commitments[c]["commodity"].iloc[0]
            if pd.isna(commodity):
                devices = m.d
            else:
                devices = problem.commodity_devices.get(commodity, set())
                if not devices:
                    return Constraint.Skip

        return (
            0 if "upwards deviation price" in commitments[c].columns else None,
            m.commitment_quantity[c, j]
            + m.commitment_downwards_deviation[c]
            + m.commitment_upwards_deviation[c]
            - sum(m.ems_power[d, j] for d in devices),
            0 if "downwards deviation price" in commitments[c].columns else None,
        )

    def device_derivative_equalities(m, d, j):
        """Couple device flows to EMS flows per device."""
        return (
            0,
            m.device_power_up[d, j] + m.device_power_down[d, j] - m.ems_power[d, j],
            0,
        )

    model.grouped_commitment_equalities = Constraint(
        model.cjg, rule=grouped_commitment_equalities
    )

    model.group_stock_balance = Constraint(model.sg, model.j, rule=group_stock_balance)
    model.device_energy_bounds = Constraint(model.d, model.j, rule=device_bounds)
    model.device_power_bounds = Constraint(
        model.d, model.j, rule=device_derivative_bounds
    )
    model.device_power_down_bounds = Constraint(
        model.d, model.j, rule=device_down_derivative_bounds
    )
    model.device_power_up_bounds = Constraint(
        model.d, model.j, rule=device_up_derivative_bounds
    )
    model.device_power_up_sign = Constraint(
        model.d, model.j, rule=device_up_derivative_sign
    )
    model.device_power_down_sign = Constraint(
        model.d, model.j, rule=device_down_derivative_sign
    )
    model.ems_power_bounds = Constraint(model.eg, model.j, rule=ems_derivative_bounds)
    if not convex_cost_curve:
        model.commitment_up_derivative_sign_con = Constraint(
            model.c, rule=commitment_up_derivative_sign
        )
        model.commitment_down_derivative_sign_con = Constraint(
            model.c, rule=commitment_down_derivative_sign
        )
    model.ems_power_commitment_equalities = Constraint(
        model.cj, rule=ems_flow_commitment_equalities
    )

    model.device_power_equalities = Constraint(
        model.d, model.j, rule=device_derivative_equalities
    )

    if coupling_device_specs:
        n_coupling_groups = len(coupling_groups)

        # One free variable per group per time step: the common normalised flow.
        model.coupling_group_range = RangeSet(0, n_coupling_groups - 1)
        model.coupling_alpha = Var(model.coupling_group_range, model.j, domain=Reals)

        model.coupling_device_range = RangeSet(0, len(coupling_device_specs) - 1)

        def flow_coupling_rule(m, c, j):
            """Enforce P[d, j] == coeff * alpha[group, j] for each coupled device.

            This pins every device's flow to the same normalised level ``alpha``,
            scaled by its coupling coefficient. The coefficient sign indicates direction:
            positive for inputs (consuming), negative for outputs (producing).
            """
            g, d, coeff = coupling_device_specs[c]
            return m.ems_power[d, j] == coeff * m.coupling_alpha[g, j]

        model.flow_coupling_constraints = Constraint(
            model.coupling_device_range, model.j, rule=flow_coupling_rule
        )

    if balance_group_specs:
        model.balance_group_range = RangeSet(0, len(balance_group_specs) - 1)

        def node_balance_rule(m, b, j):
            """Balance the power flows of an internal commodity node at every time step.

            Everything produced into the node must be consumed from it within the same time step.
            The balance sums the devices' commodity-side flows (ems_power);
            derivative efficiencies and stock deltas describe each device's own stock-side conversion (e.g. of a shared buffer),
            and do not enter the commodity balance.
            """
            return (
                0,
                sum(m.ems_power[d, j] for d in balance_group_specs[b]),
                0,
            )

        model.node_balance_constraints = Constraint(
            model.balance_group_range, model.j, rule=node_balance_rule
        )

    # Power bands (S2 operation modes): a banded device must operate within
    # exactly one of its declared signed power ranges at every time step.
    # Which band it runs in (per time step) is a free binary decision variable;
    # the constraints below only tie the device's power to the chosen band.
    model.bd = Set(
        initialize=sorted(band_lookup.keys()),
        doc="Set of devices with power bands",
    )
    model.db = Set(
        dimen=2,
        initialize=lambda m: (
            (d, b) for d, bands in band_lookup.items() for b in range(len(bands))
        ),
        doc="Set of (device, band) pairs for devices with power bands",
    )
    model.device_band = Var(model.db, model.j, domain=Binary, initialize=0)

    def device_band_choice(m, d, j):
        """Each banded device runs in exactly one band per time step."""
        return sum(m.device_band[d, b, j] for b in range(len(band_lookup[d]))) == 1

    def device_band_power_lower(m, d, j):
        """Device power at least the chosen band's minimum.

        Exactly one band binary is 1 (see device_band_choice), so the sum
        selects the minimum of the chosen band.
        """
        return m.device_power_down[d, j] + m.device_power_up[d, j] >= sum(
            m.device_band[d, b, j] * band_lookup[d][b][0]
            for b in range(len(band_lookup[d]))
        )

    def device_band_power_upper(m, d, j):
        """Device power at most the chosen band's maximum.

        Exactly one band binary is 1 (see device_band_choice), so the sum
        selects the maximum of the chosen band.
        """
        return m.device_power_down[d, j] + m.device_power_up[d, j] <= sum(
            m.device_band[d, b, j] * band_lookup[d][b][1]
            for b in range(len(band_lookup[d]))
        )

    model.device_band_choice = Constraint(model.bd, model.j, rule=device_band_choice)
    model.device_band_power_lower = Constraint(
        model.bd, model.j, rule=device_band_power_lower
    )
    model.device_band_power_upper = Constraint(
        model.bd, model.j, rule=device_band_power_upper
    )

    # Add objective
    def cost_function(m):
        costs = 0
        m.commitment_costs = {
            c: m.commitment_downwards_deviation[c] * m.down_price[c]
            + m.commitment_upwards_deviation[c] * m.up_price[c]
            for c in m.c
        }
        for c in m.c:
            costs += m.commitment_costs[c]
        return costs

    model.costs = Objective(rule=cost_function, sense=minimize)

    # Solve
    solver_name = current_app.config.get("FLEXMEASURES_LP_SOLVER")

    solver = SolverFactory(solver_name)

    # Temporary fix for https://github.com/Pyomo/pyomo/issues/3841
    if solver_name == "cbc":
        import shutil

        cbc_path = shutil.which("cbc") or shutil.which("Cbc")
        if cbc_path is not None:
            solver.set_executable(cbc_path)

    # Tight tolerances for HiGHS, then operator-configured options last
    # (shared with the direct HiGHS backend, so both apply the same settings).
    for option_name, option_value in solver_options(solver_name).items():
        solver.options[option_name] = option_value

    # load_solutions=False to avoid a RuntimeError exception in appsi solvers when solving an infeasible problem.
    results = solver.solve(model, load_solutions=False)

    # load the results only if a feasible solution has been found
    if len(results.solution) > 0:
        model.solutions.load_from(results)

    planned_costs = value(model.costs)
    subcommitment_costs = {g: value(cost) for g, cost in model.commitment_costs.items()}

    planned_power = planned_power_per_device(
        ([model.ems_power[d, j].value for j in model.j] for d in model.d),
        start,
        end,
        resolution,
    )

    model.commitment_costs = aggregate_subcommitment_costs(
        subcommitment_costs, commitment_mapping
    )
    model.commodity_costs = aggregate_commodity_costs(commitments, subcommitment_costs)

    # model.pprint()
    # model.display()
    # print(results.solver.termination_condition)
    # print(planned_costs)
    return planned_power, planned_costs, results, model
