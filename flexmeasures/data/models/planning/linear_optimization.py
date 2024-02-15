from __future__ import annotations

from flask import current_app
import pandas as pd
import numpy as np
from pandas.tseries.frequencies import to_offset
from pyomo.core import (
    ConcreteModel,
    Var,
    RangeSet,
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

from flexmeasures.data.models.planning.utils import initialize_series
from flexmeasures.utils.calculations import apply_stock_changes_and_losses

infinity = float("inf")


def device_scheduler(  # noqa C901
    device_constraints: list[pd.DataFrame],
    ems_constraints: pd.DataFrame,
    commitment_quantities: list[pd.Series],
    commitment_downwards_deviation_price: list[pd.Series] | list[float],
    commitment_upwards_deviation_price: list[pd.Series] | list[float],
    initial_stock: float = 0,
) -> tuple[list[pd.Series], float, SolverResults, ConcreteModel]:
    """This generic device scheduler is able to handle an EMS with multiple devices,
    with various types of constraints on the EMS level and on the device level,
    and with multiple market commitments on the EMS level.
    A typical example is a house with many devices.
    The commitments are assumed to be with regard to the flow of energy to the device (positive for consumption,
    negative for production). The solver minimises the costs of deviating from the commitments.

    Device constraints are on a device level. Handled constraints (listed by column name):
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
    EMS constraints are on an EMS level. Handled constraints (listed by column name):
        derivative max: maximum flow
        derivative min: minimum flow
    Commitments are on an EMS level. Parameter explanations:
        commitment_quantities: amounts of flow specified in commitments (both previously ordered and newly requested)
            - e.g. in MW or boxes/h
        commitment_downwards_deviation_price: penalty for downwards deviations of the flow
            - e.g. in EUR/MW or EUR/(boxes/h)
            - either a single value (same value for each flow value) or a Series (different value for each flow value)
        commitment_upwards_deviation_price: penalty for upwards deviations of the flow

    All Series and DataFrames should have the same resolution.

    For now, we pass in the various constraints and prices as separate variables, from which we make a MultiIndex
    DataFrame. Later we could pass in a MultiIndex DataFrame directly.
    """

    model = ConcreteModel()

    # If the EMS has no devices, don't bother
    if len(device_constraints) == 0:
        return [], 0, SolverResults(), model

    # Check if commitments have the same time window and resolution as the constraints
    start = device_constraints[0].index.to_pydatetime()[0]
    # Workaround for https://github.com/pandas-dev/pandas/issues/53643. Was: resolution = pd.to_timedelta(device_constraints[0].index.freq)
    resolution = pd.to_timedelta(device_constraints[0].index.freq).to_pytimedelta()
    end = device_constraints[0].index.to_pydatetime()[-1] + resolution
    if len(commitment_quantities) != 0:
        start_c = commitment_quantities[0].index.to_pydatetime()[0]
        resolution_c = pd.to_timedelta(commitment_quantities[0].index.freq)
        end_c = commitment_quantities[0].index.to_pydatetime()[-1] + resolution
        if not (start_c == start and end_c == end):
            raise Exception(
                "Not implemented for different time windows.\n(%s,%s)\n(%s,%s)"
                % (start, end, start_c, end_c)
            )
        if resolution_c != resolution:
            raise Exception(
                "Not implemented for different resolutions.\n%s\n%s"
                % (resolution, resolution_c)
            )

    bigM_columns = ["derivative max", "derivative min", "derivative equals"]
    # Compute a good value for M
    M = np.nanmax([np.nanmax(d[bigM_columns].abs()) for d in device_constraints])

    # M has to be 1 MW, at least
    M = max(M, 1)

    for d in range(len(device_constraints)):
        if "stock delta" not in device_constraints[d].columns:
            device_constraints[d]["stock delta"] = 0
        else:
            device_constraints[d]["stock delta"] = device_constraints[d][
                "stock delta"
            ].fillna(0)

    # Turn prices per commitment into prices per commitment flow
    if len(commitment_downwards_deviation_price) != 0:
        if all(
            isinstance(price, float) for price in commitment_downwards_deviation_price
        ):
            commitment_downwards_deviation_price = [
                initialize_series(price, start, end, resolution)
                for price in commitment_downwards_deviation_price
            ]
    if len(commitment_upwards_deviation_price) != 0:
        if all(
            isinstance(price, float) for price in commitment_upwards_deviation_price
        ):
            commitment_upwards_deviation_price = [
                initialize_series(price, start, end, resolution)
                for price in commitment_upwards_deviation_price
            ]

    # Add indices for devices (d), datetimes (j) and commitments (c)
    model.d = RangeSet(0, len(device_constraints) - 1, doc="Set of devices")
    model.j = RangeSet(
        0, len(device_constraints[0].index.to_pydatetime()) - 1, doc="Set of datetimes"
    )
    model.c = RangeSet(0, len(commitment_quantities) - 1, doc="Set of commitments")

    # Add parameters
    def price_down_select(m, c, j):
        return commitment_downwards_deviation_price[c].iloc[j]

    def price_up_select(m, c, j):
        return commitment_upwards_deviation_price[c].iloc[j]

    def commitment_quantity_select(m, c, j):
        return commitment_quantities[c].iloc[j]

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

    def ems_derivative_max_select(m, j):
        v = ems_constraints["derivative max"].iloc[j]
        if np.isnan(v):
            return infinity
        else:
            return v

    def ems_derivative_min_select(m, j):
        v = ems_constraints["derivative min"].iloc[j]
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

    model.up_price = Param(model.c, model.j, initialize=price_up_select)
    model.down_price = Param(model.c, model.j, initialize=price_down_select)
    model.commitment_quantity = Param(
        model.c, model.j, initialize=commitment_quantity_select
    )
    model.device_max = Param(model.d, model.j, initialize=device_max_select)
    model.device_min = Param(model.d, model.j, initialize=device_min_select)
    model.device_derivative_max = Param(
        model.d, model.j, initialize=device_derivative_max_select
    )
    model.device_derivative_min = Param(
        model.d, model.j, initialize=device_derivative_min_select
    )
    model.ems_derivative_max = Param(model.j, initialize=ems_derivative_max_select)
    model.ems_derivative_min = Param(model.j, initialize=ems_derivative_min_select)
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
    model.commitment_downwards_deviation = Var(
        model.c, model.j, domain=NonPositiveReals, initialize=0
    )
    model.commitment_upwards_deviation = Var(
        model.c, model.j, domain=NonNegativeReals, initialize=0
    )

    # Add constraints as a tuple of (lower bound, value, upper bound)
    def device_bounds(m, d, j):
        """Apply conversion efficiencies to conversion from flow to stock change and vice versa,
        and apply storage efficiencies to stock levels from one datetime to the next."""
        stock_changes = [
            (
                m.device_power_down[d, k] / m.device_derivative_down_efficiency[d, k]
                + m.device_power_up[d, k] * m.device_derivative_up_efficiency[d, k]
                + m.stock_delta[d, k]
            )
            for k in range(0, j + 1)
        ]
        efficiencies = [m.device_efficiency[d, k] for k in range(0, j + 1)]
        return (
            m.device_min[d, j],
            [
                stock - initial_stock
                for stock in apply_stock_changes_and_losses(
                    initial_stock, stock_changes, efficiencies
                )
            ][-1],
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

    def device_up_derivative_sign(m, d, j):
        """Derivative up if sign points up, derivative not up if sign points down."""
        return m.device_power_up[d, j] <= M * m.device_power_sign[d, j]

    def device_down_derivative_sign(m, d, j):
        """Derivative down if sign points down, derivative not down if sign points up."""
        return -m.device_power_down[d, j] <= M * (1 - m.device_power_sign[d, j])

    def ems_derivative_bounds(m, j):
        return m.ems_derivative_min[j], sum(m.ems_power[:, j]), m.ems_derivative_max[j]

    def ems_flow_commitment_equalities(m, j):
        """Couple EMS flows (sum over devices) to commitments."""
        return (
            0,
            sum(m.commitment_quantity[:, j])
            + sum(m.commitment_downwards_deviation[:, j])
            + sum(m.commitment_upwards_deviation[:, j])
            - sum(m.ems_power[:, j]),
            0,
        )

    def device_derivative_equalities(m, d, j):
        """Couple device flows to EMS flows per device."""
        return (
            0,
            m.device_power_up[d, j] + m.device_power_down[d, j] - m.ems_power[d, j],
            0,
        )

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
    model.ems_power_bounds = Constraint(model.j, rule=ems_derivative_bounds)
    model.ems_power_commitment_equalities = Constraint(
        model.j, rule=ems_flow_commitment_equalities
    )
    model.device_power_equalities = Constraint(
        model.d, model.j, rule=device_derivative_equalities
    )

    # Add objective
    def cost_function(m):
        costs = 0
        for c in m.c:
            for j in m.j:
                costs += m.commitment_downwards_deviation[c, j] * m.down_price[c, j]
                costs += m.commitment_upwards_deviation[c, j] * m.up_price[c, j]
        return costs

    model.costs = Objective(rule=cost_function, sense=minimize)

    # Solve
    solver_name = current_app.config.get("FLEXMEASURES_LP_SOLVER")

    solver = SolverFactory(solver_name)

    # disable logs for the HiGHS solver in case that LOGGING_LEVEL is INFO
    if current_app.config["LOGGING_LEVEL"] == "INFO" and (
        "highs" in solver_name.lower()
    ):
        solver.options["output_flag"] = "false"

    # load_solutions=False to avoid a RuntimeError exception in appsi solvers when solving an infeasible problem.
    results = solver.solve(model, load_solutions=False)

    # load the results only if a feasible solution has been found
    if len(results.solution) > 0:
        model.solutions.load_from(results)

    planned_costs = value(model.costs)
    planned_power_per_device = []
    for d in model.d:
        planned_device_power = [model.ems_power[d, j].value for j in model.j]
        planned_power_per_device.append(
            initialize_series(
                data=planned_device_power,
                start=start,
                end=end,
                resolution=to_offset(resolution),
            )
        )

    # model.pprint()
    # model.display()
    # print(results.solver.termination_condition)
    # print(planned_costs)
    return planned_power_per_device, planned_costs, results, model
