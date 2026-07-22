from __future__ import annotations

import math

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

infinity = float("inf")


def validate_highs_options(options: dict) -> None:
    """Raise if HiGHS would refuse any of these options.

    Pyomo's appsi_highs interface applies solver options without checking HiGHS'
    return status, so an unknown name, an invalid value, or a feature missing from
    the installed HiGHS build is otherwise ignored without a word. That silently
    turns a mis-typed option into a no-op, and a benchmark of it into a false
    negative. Probing a throwaway Highs instance surfaces the rejection instead.
    """
    try:
        import highspy
    except ImportError:
        # Solver named "*highs*" but highspy absent: let the solver interface complain.
        return

    probe = highspy.Highs()
    probe.setOptionValue("output_flag", False)
    rejected = [
        f"{name}={value!r}"
        for name, value in options.items()
        if probe.setOptionValue(name, value) != highspy.HighsStatus.kOk
    ]
    if rejected:
        raise ValueError(
            f"HiGHS rejected these FLEXMEASURES_LP_SOLVER_OPTIONS: {', '.join(rejected)}."
            " The option name may be unknown, the value invalid, or the feature absent"
            " from this HiGHS build. For example, the HiPO solver (solver='hipo') needs"
            " a HiGHS built against BLAS and METIS, which the pip-installed highspy is not."
        )

    if "threads" in options or "parallel" in options:
        current_app.logger.warning(
            "FLEXMEASURES_LP_SOLVER_OPTIONS sets 'threads' and/or 'parallel'. HiGHS"
            " initializes its thread scheduler once per process, so inside a long-lived"
            " worker only the first solve honours these; later solves fail with 'global"
            " scheduler has already been initialized' and yield no schedule."
        )


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
    ems_constraint_groups: list[list[int]] | None = None,
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

    # Normalise EMS constraints to a list of (DataFrame, device-group) pairs.
    # A single DataFrame (legacy behaviour) applies to the summed flow of all devices;
    # a list of DataFrames applies one EMS-level constraint per device group, as set up
    # per commodity by the StorageScheduler.
    all_devices = list(range(len(device_constraints)))
    if isinstance(ems_constraints, pd.DataFrame):
        ems_constraints_list = [ems_constraints]
        ems_constraint_device_groups = [all_devices]
    else:
        ems_constraints_list = ems_constraints
        if ems_constraint_groups is None:
            if len(ems_constraints_list) > 1:
                raise ValueError(
                    "When passing multiple EMS constraint DataFrames, you must also specify ems_constraint_groups."
                )
            ems_constraint_device_groups = [all_devices for _ in ems_constraints_list]
        else:
            ems_constraint_device_groups = ems_constraint_groups

    # map device -> primary stock group (used for per-device stock bounds)
    # and map stock group -> all member devices (used for stock accumulation).
    device_to_group = {}
    group_to_devices: dict[str, list[int]] = {}

    # Group keys are namespaced strings: a declared stock group's key (a state-of-charge
    # sensor id) could otherwise collide with the device index of an ungrouped device,
    # silently merging that device into the stock group.
    #
    # A device may belong to more than one stock group — a commodity converter (e.g. a
    # steamer bridging a heat node and a steam node) participates in every node it
    # touches, so ``group_to_devices`` keeps the full (possibly overlapping) membership.
    # ``device_to_group`` records only the primary group (first assignment wins), used
    # where a single owning group is needed (per-device stock bounds).
    if stock_groups:
        for g, devices in stock_groups.items():
            gkey = f"stock:{g}"
            group_to_devices[gkey] = list(devices)
            for d in devices:
                device_to_group.setdefault(d, gkey)
    # Devices not in any stock group (e.g. inflexible devices) form individual groups.
    for d in range(len(device_constraints)):
        if d not in device_to_group:
            gkey = f"device:{d}"
            device_to_group[d] = gkey
            group_to_devices[gkey] = [d]

    # The stock recursion is modelled once per stock group, using the group's shared
    # storage efficiency, so devices sharing a stock may not declare different ones.
    for g, group_devices in group_to_devices.items():
        if len(group_devices) > 1:
            # A missing efficiency column means the default (no losses) applies.
            group_efficiency = device_constraints[group_devices[0]].get("efficiency")
            for d in group_devices[1:]:
                efficiency = device_constraints[d].get("efficiency")
                if (
                    (efficiency is None) != (group_efficiency is None)
                    or efficiency is not None
                    and not efficiency.equals(group_efficiency)
                ):
                    raise ValueError(
                        f"Devices {group_devices} share stock group {g} but have different"
                        " storage efficiencies. The storage efficiency is a property of the"
                        " shared stock, so define it once per stock group."
                    )
            if isinstance(initial_stock, list):
                group_initial_stocks = {
                    initial_stock[d] if d < len(initial_stock) else 0
                    for d in group_devices
                }
                if len(group_initial_stocks) > 1:
                    raise ValueError(
                        f"Devices {group_devices} share stock group {g} but have different"
                        " initial stocks. The initial stock is a property of the shared"
                        " stock, so define it once per stock group."
                    )

    # Collect (group_index, device_index, coefficient) triples for coupling constraints.
    # Each device in each group will be constrained: P[d, j] == coeff * alpha[group, j]
    # where alpha is a free variable representing the common normalised flow.
    coupling_device_specs: list[tuple[int, int, float]] = []
    if coupling_groups:
        for g_idx, (_group_name, members) in enumerate(coupling_groups.items()):
            for d_idx, coeff in members:
                coupling_device_specs.append((g_idx, d_idx, coeff))

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
        # Stock-scoped commitments couple to their stock group as a whole, regardless
        # of which device index they name: the group's first device carries the group's
        # stock, so a single-member group suffices (also avoiding double-counting the
        # shared stock when the commitment names multiple members).
        if "stock" in df.columns and pd.notna(df["stock"].iloc[0]):
            stock_group_key = f"stock:{int(df['stock'].iloc[0])}"
            if stock_group_key in group_to_devices:
                device_group_lookup[c] = {
                    stock_group_key: {group_to_devices[stock_group_key][0]}
                }
                continue

        if "device" not in df.columns:
            # EMS-level commitment: no device grouping needed here;
            # handled by ems_flow_commitment_equalities.
            continue

        has_device_group = "device_group" in df.columns
        if has_device_group:
            rows = df[["device", "device_group"]].dropna()
        else:
            # Backwards-compatible default: each device is its own group.
            # This preserves the behaviour of old-style DataFrame commitments that
            # pre-date the device_group feature (e.g. from initialize_device_commitment).
            rows = df[["device"]].dropna()

        device_group_lookup[c] = {}

        for _, row in rows.iterrows():
            d = row["device"]
            # When no device_group column is present, use the device id itself as
            # the group label so that each device forms an independent group.
            g = row["device_group"] if has_device_group else d

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

    def _initial_stock_of(d):
        if isinstance(initial_stock, list):
            # No initial stock defined for inflexible device
            return initial_stock[d] if d < len(initial_stock) else 0
        return initial_stock

    def _stock_change_at(m, g, j):
        """Stock change of stock group g during time step j (before losses)."""
        return sum(
            m.device_power_down[dev, j] / m.device_derivative_down_efficiency[dev, j]
            + m.device_power_up[dev, j] * m.device_derivative_up_efficiency[dev, j]
            + m.stock_delta[dev, j]
            for dev in group_to_devices[g]
        )

    def _loss_coefficients(efficiency: float) -> tuple[float, float]:
        """Coefficients (a, b) of one step of the stock recursion, for `how="linear"`.

        stock[j] = a * stock[j-1] + b * change[j]

        Mirrors :func:`apply_stock_changes_and_losses`, which we cannot call here
        because it expects numbers, while `change[j]` is a Pyomo expression. The
        storage efficiency is a Param, so `a` and `b` are plain floats.
        """
        if efficiency == 1:
            return 1.0, 1.0
        return efficiency, (efficiency - 1) / math.log(efficiency)

    def group_stock_balance(m, g, j):
        """Recursively couple a stock group's stock to the previous step's stock.

        Expressing stock[j] as a running sum over all k <= j (as this once did) makes
        the number of nonzeros grow quadratically with the scheduling horizon. The
        recursion below is equivalent and keeps it linear.

        The group's devices share their storage efficiency and initial stock
        (validated above), so the first device can represent the group here.
        """
        d0 = group_to_devices[g][0]
        a, b = _loss_coefficients(m.device_efficiency[d0, j])
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

    def device_up_derivative_sign(m, d, j):
        """Derivative up if sign points up, derivative not up if sign points down."""
        return m.device_power_up[d, j] <= Md * m.device_power_sign[d, j]

    def device_down_derivative_sign(m, d, j):
        """Derivative down if sign points down, derivative not down if sign points up."""
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

        # Legacy behavior: no commodity → sum over all devices
        if "commodity" not in commitments[c].columns:
            devices = m.d
        else:
            commodity = commitments[c]["commodity"].iloc[0]
            if pd.isna(commodity):
                devices = m.d
            else:
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

    # Set tight tolerance for HiGHS solver
    profile = {}
    if "highs" in solver_name.lower():
        profile = {
            "mip_rel_gap": "0",
            "mip_abs_gap": "0",
            "primal_feasibility_tolerance": "1e-9",
            "dual_feasibility_tolerance": "1e-9",
            "mip_feasibility_tolerance": "1e-9",
        }
        # disable logs for the HiGHS solver in case that LOGGING_LEVEL is INFO
        if current_app.config["LOGGING_LEVEL"] == "INFO":
            profile["output_flag"] = "false"

    # Apply operator-configured options last, so they override the defaults above.
    configured_options = current_app.config.get("FLEXMEASURES_LP_SOLVER_OPTIONS") or {}
    if configured_options and "highs" in solver_name.lower():
        validate_highs_options(configured_options)
    profile.update(configured_options)

    for option_name, option_value in profile.items():
        solver.options[option_name] = option_value

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
