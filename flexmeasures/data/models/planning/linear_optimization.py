from __future__ import annotations

from flask import current_app
import pandas as pd
import numpy as np
from pandas.tseries.frequencies import to_offset
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
from flexmeasures.data.models.planning.utils import initialize_series, initialize_df
from flexmeasures.utils.calculations import apply_stock_changes_and_losses

infinity = float("inf")


def device_scheduler(  # noqa C901
    device_constraints: list[pd.DataFrame],
    ems_constraints: pd.DataFrame,
    commitment_quantities: list[pd.Series] | None = None,
    commitment_downwards_deviation_price: list[pd.Series] | list[float] | None = None,
    commitment_upwards_deviation_price: list[pd.Series] | list[float] | None = None,
    commitments: list[pd.DataFrame] | list[Commitment] | None = None,
    initial_stock: float | list[float] = 0,
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
    :param commitments:         Commitments are on an EMS level by default. Handled parameters (listed by column name):
                                    quantity:                   for example, 5.5
                                    downwards deviation price:  10.1
                                    upwards deviation price:    10.2
                                    group:                      1 (defaults to the enumerate time step j)
                                    device:                     0 (corresponds to device d; if not set, commitment is on an EMS level)
    :param initial_stock:       initial stock for each device. Use a list with the same number of devices as device_constraints,
                                or use a single value to set the initial stock to be the same for all devices.

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

    model = ConcreteModel()

    # If the EMS has no devices, don't bother
    if len(device_constraints) == 0:
        return [], 0, SolverResults(), model

    # Get timing from first device
    start = device_constraints[0].index.to_pydatetime()[0]
    # Workaround for https://github.com/pandas-dev/pandas/issues/53643. Was: resolution = pd.to_timedelta(device_constraints[0].index.freq)
    resolution = pd.to_timedelta(device_constraints[0].index.freq).to_pytimedelta()
    end = device_constraints[0].index.to_pydatetime()[-1] + resolution

    # Move commitments from old structure to new
    if commitments is None:
        commitments = []
    else:
        commitments = [
            c.to_frame() if isinstance(c, Commitment) else c for c in commitments
        ]
    if commitment_quantities is not None:
        for quantity, down, up in zip(
            commitment_quantities,
            commitment_downwards_deviation_price,
            commitment_upwards_deviation_price,
        ):

            # Turn prices per commitment into prices per commitment flow
            if all(isinstance(price, float) for price in down) or isinstance(
                down, float
            ):
                down = initialize_series(down, start, end, resolution)
            if all(isinstance(price, float) for price in up) or isinstance(up, float):
                up = initialize_series(up, start, end, resolution)

            group = initialize_series(list(range(len(down))), start, end, resolution)
            df = initialize_df(
                ["quantity", "downwards deviation price", "upwards deviation price"],
                start,
                end,
                resolution,
            )
            df["quantity"] = quantity
            df["downwards deviation price"] = down
            df["upwards deviation price"] = up
            df["group"] = group
            commitments.append(df)

    # commodity → set(device indices)
    commodity_devices = {}

    for df in commitments:
        if "commodity" not in df.columns or "device" not in df.columns:
            continue

        for _, row in df[["commodity", "device"]].dropna().iterrows():
            devices = row["device"]
            if not isinstance(devices, (list, tuple, set)):
                devices = [devices]

            commodity_devices.setdefault(row["commodity"], set()).update(devices)

    # Check if commitments have the same time window and resolution as the constraints
    for commitment in commitments:
        start_c = commitment.index.to_pydatetime()[0]
        resolution_c = pd.to_timedelta(commitment.index.freq)
        end_c = commitment.index.to_pydatetime()[-1] + resolution
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

    def convert_commitments_to_subcommitments(
        dfs: list[pd.DataFrame],
    ) -> tuple[list[pd.DataFrame], dict[int, int]]:
        """Transform commitments, each specifying a group for each time step, to sub-commitments, one per group.

        'Groups' are a commitment concept (grouping time slots of a commitment),
        making it possible that deviations/breaches can be accounted for properly within this group
        (e.g. highest breach per calendar month defines the penalty).
        Here, we define sub-commitments, by separating commitments by group and by direction of deviation (up, down).

        We also enumerate the time steps in a new column "j".

        For example, given contracts A and B (represented by 2 DataFrames), each with 3 groups,
        we return (sub)commitments A1, A2, A3, B1, B2 and B3,
        where A,B,C is the enumerated contract and 1,2,3 is the enumerated group.
        """
        commitment_mapping = {}
        sub_commitments = []
        for c, df in enumerate(dfs):
            # Make sure each commitment has "device" (default NaN) and "class" (default FlowCommitment) columns
            if "device" not in df.columns:
                df["device"] = np.nan
            if "class" not in df.columns:
                df["class"] = FlowCommitment

            df["j"] = range(len(df.index))
            groups = list(df["group"].unique())
            for group in groups:
                sub_commitment = df[df["group"] == group].drop(columns=["group"])

                # Catch non-uniqueness
                if len(sub_commitment["upwards deviation price"].unique()) > 1:
                    raise ValueError(
                        "Commitment groups cannot have non-unique upwards deviation prices."
                    )
                if len(sub_commitment["downwards deviation price"].unique()) > 1:
                    raise ValueError(
                        "Commitment groups cannot have non-unique downwards deviation prices."
                    )
                if len(sub_commitment) == 1:
                    commitment_mapping[len(sub_commitments)] = c
                    sub_commitments.append(sub_commitment)
                else:
                    down_commitment = sub_commitment.copy().drop(
                        columns="upwards deviation price"
                    )
                    up_commitment = sub_commitment.copy().drop(
                        columns="downwards deviation price"
                    )
                    commitment_mapping[len(sub_commitments)] = c
                    commitment_mapping[len(sub_commitments) + 1] = c
                    sub_commitments.extend([down_commitment, up_commitment])
        return sub_commitments, commitment_mapping

    commitments, commitment_mapping = convert_commitments_to_subcommitments(commitments)

    device_group_lookup = {}

    for c, df in enumerate(commitments):
        if "device_group" not in df.columns or "device" not in df.columns:
            continue

        rows = df[["device", "device_group"]].dropna()

        device_group_lookup[c] = {}

        for _, row in rows.iterrows():
            g = row["device_group"]
            d = row["device"]

            if isinstance(d, (list, tuple, set, np.ndarray)):
                devices = set(d)
            else:
                devices = {d}

            device_group_lookup[c].setdefault(g, set()).update(devices)

    # Oversimplified check for a convex cost curve
    df = pd.concat(commitments)[
        ["upwards deviation price", "downwards deviation price"]
    ]
    df = df.groupby(level=0).sum()
    if len(df[df["upwards deviation price"] < df["downwards deviation price"]]) == 0:
        convex_cost_curve = True
    else:
        convex_cost_curve = False

    bigM_columns = ["derivative max", "derivative min", "derivative equals"]
    # Compute a good value for our Big-Ms
    # Md is used to constrain the search space for device power
    # Mc is used to constrain the search space for commitment deviations
    Md = np.nanmax([np.nanmax(d[bigM_columns].abs()) for d in device_constraints])
    Mc = np.nansum([np.nansum(d[bigM_columns].abs()) for d in device_constraints])

    # Both Md and Mc have to be 1 MW, at least
    Md = max(Md, 1)
    Mc = max(Mc, 1)

    for d in range(len(device_constraints)):
        if "stock delta" not in device_constraints[d].columns:
            device_constraints[d]["stock delta"] = 0
        else:
            device_constraints[d]["stock delta"] = (
                device_constraints[d]["stock delta"].astype(float).fillna(0)
            )

    # Add indices for devices (d), datetimes (j) and commitments (c)
    model.d = RangeSet(0, len(device_constraints) - 1, doc="Set of devices")
    model.j = RangeSet(
        0, len(device_constraints[0].index.to_pydatetime()) - 1, doc="Set of datetimes"
    )
    model.c = RangeSet(0, len(commitments) - 1, doc="Set of commitments")

    def commitment_device_groups_init(m):
        return ((c, g) for c, groups in device_group_lookup.items() for g in groups)

    model.cg = Set(dimen=2, initialize=commitment_device_groups_init)

    def commitments_init(m):
        return ((c, j) for c in m.c for j in commitments[c]["j"])

    model.cj = Set(dimen=2, initialize=commitments_init)

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

    def _get_stock_change(m, d, j):
        """Determine final stock change of device d until time j.

        Apply conversion efficiencies to conversion from flow to stock change and vice versa,
        and apply storage efficiencies to stock levels from one datetime to the next.
        """
        if isinstance(initial_stock, list):
            # No initial stock defined for inflexible device
            initial_stock_d = initial_stock[d] if d < len(initial_stock) else 0
        else:
            initial_stock_d = initial_stock

        stock_changes = [
            (
                m.device_power_down[d, k] / m.device_derivative_down_efficiency[d, k]
                + m.device_power_up[d, k] * m.device_derivative_up_efficiency[d, k]
                + m.stock_delta[d, k]
            )
            for k in range(0, j + 1)
        ]
        efficiencies = [m.device_efficiency[d, k] for k in range(0, j + 1)]
        final_stock_change = [
            stock - initial_stock_d
            for stock in apply_stock_changes_and_losses(
                initial_stock_d, stock_changes, efficiencies
            )
        ][-1]
        return final_stock_change

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

    def device_up_derivative_sign(m, d, j):
        """Derivative up if sign points up, derivative not up if sign points down."""
        return m.device_power_up[d, j] <= Md * m.device_power_sign[d, j]

    def device_down_derivative_sign(m, d, j):
        """Derivative down if sign points down, derivative not down if sign points up."""
        return -m.device_power_down[d, j] <= Md * (1 - m.device_power_sign[d, j])

    def ems_derivative_bounds(m, j):
        return m.ems_derivative_min[j], sum(m.ems_power[:, j]), m.ems_derivative_max[j]

    def commitment_up_derivative_sign(m, c):
        """Up deviation active only if sign points up."""
        return m.commitment_upwards_deviation[c] <= Mc * m.commitment_sign[c]

    def commitment_down_derivative_sign(m, c):
        """Down deviation active only if sign points down."""
        return -m.commitment_downwards_deviation[c] <= Mc * (1 - m.commitment_sign[c])

    def device_stock_commitment_equalities(m, c, j, d):
        """Couple device stocks to each commitment."""
        if (
            "device" not in commitments[c].columns
            or (commitments[c]["device"] != d).all()
            or m.commitment_quantity[c, j] == -infinity
        ):
            # Commitment c does not concern device d
            return Constraint.Skip

        # Determine center part of the lhs <= center part <= rhs constraint
        center_part = (
            m.commitment_quantity[c, j]
            + m.commitment_downwards_deviation[c]
            + m.commitment_upwards_deviation[c]
        )
        if commitments[c]["class"].apply(lambda cl: cl == StockCommitment).all():
            center_part -= _get_stock_change(m, d, j)
        elif commitments[c]["class"].apply(lambda cl: cl == FlowCommitment).all():
            center_part -= m.ems_power[d, j]
        else:
            raise NotImplementedError("Unknown commitment class")
        return (
            0 if "upwards deviation price" in commitments[c].columns else None,
            center_part,
            0 if "downwards deviation price" in commitments[c].columns else None,
        )

    def ems_flow_commitment_equalities(m, c, j):
        """
        Enforce an EMS-level flow commitment for a given commodity.

        Couples the commitment baseline (plus deviation variables) to the sum of EMS
        power over all devices belonging to the commitment’s commodity. Skips
        non-flow commitments or commodities without associated devices.
        """
        if commitments[c]["class"].iloc[0] != FlowCommitment:
            return Constraint.Skip

        commodity = (
            commitments[c]["commodity"].iloc[0]
            if "commodity" in commitments[c].columns
            else None
        )
        devices = commodity_devices.get(commodity, set())

        if not devices:
            return Constraint.Skip

        return (
            None,
            m.commitment_quantity[c, j]
            + m.commitment_downwards_deviation[c]
            + m.commitment_upwards_deviation[c]
            - sum(m.ems_power[d, j] for d in devices),
            None,
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
    subcommitment_costs = {g: value(cost) for g, cost in model.commitment_costs.items()}
    commitment_costs = {}

    # Map subcommitment costs to commitments
    for g, v in subcommitment_costs.items():
        c = commitment_mapping[g]
        commitment_costs[c] = commitment_costs.get(c, 0) + v

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

    model.commitment_costs = commitment_costs
    commodity_costs = {}
    for c in model.c:
        commodity = None
        if "commodity" in commitments[c].columns:
            commodity = commitments[c]["commodity"].iloc[0]
        if commodity is None or (isinstance(commodity, float) and np.isnan(commodity)):
            continue

        cost = value(
            model.commitment_downwards_deviation[c] * model.down_price[c]
            + model.commitment_upwards_deviation[c] * model.up_price[c]
        )
        commodity_costs[commodity] = commodity_costs.get(commodity, 0) + cost

    model.commodity_costs = commodity_costs

    # model.pprint()
    # model.display()
    # print(results.solver.termination_condition)
    # print(planned_costs)
    return planned_power_per_device, planned_costs, results, model
