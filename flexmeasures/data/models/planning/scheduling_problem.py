"""Solver-agnostic preparation of the device scheduler's inputs.

:func:`flexmeasures.data.models.planning.linear_optimization.device_scheduler`
(Pyomo) and
:func:`flexmeasures.data.models.planning.highspy_optimization.device_scheduler_highspy`
(direct HiGHS) build the same mathematical model in two very different
representations, so the model construction itself is necessarily written twice.
Everything *around* it is not: normalising arguments, resolving stock groups,
converting legacy commitments, deriving Big-Ms, and turning solver output back
into schedules and costs is plain pandas/numpy work with no solver in it.

Keeping that work here means the two backends cannot drift apart on input
handling — only on the model, which is what the equivalence tests in
``tests/test_highspy_equivalence.py`` compare. It also gives both backends a
single place to grow support for a new scheduling feature's *inputs*.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from functools import cached_property

import numpy as np
import pandas as pd
from flask import current_app
from pandas.tseries.frequencies import to_offset

from flexmeasures.data.models.planning import Commitment, FlowCommitment
from flexmeasures.data.models.planning.utils import initialize_df, initialize_series

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


def solver_options(solver_name: str) -> dict:
    """The solver options to apply, for the given solver.

    HiGHS (whether reached through Pyomo as ``appsi_highs`` or directly as
    ``highspy`` -- both match on "highs") gets a tight-tolerance profile, so the
    two backends cannot disagree on tolerances and silently produce different
    schedules. Operator-configured options are applied last, so they win.
    """
    is_highs = "highs" in solver_name.lower()

    profile = {}
    if is_highs:
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

    configured_options = current_app.config.get("FLEXMEASURES_LP_SOLVER_OPTIONS") or {}
    if configured_options and is_highs:
        validate_highs_options(configured_options)
    profile.update(configured_options)
    return profile


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

        # Group rows by the "group" column in order of first appearance (like
        # pd.unique), in a single pass rather than by filtering the DataFrame
        # once per group (which would scale quadratically with the number of
        # time steps, as each time step often forms its own group).
        grouped = df.drop(columns=["group"]).groupby(df["group"], sort=False)

        # Catch non-uniqueness (vectorized across all groups)
        if (grouped["upwards deviation price"].nunique(dropna=False) > 1).any():
            raise ValueError(
                "Commitment groups cannot have non-unique upwards deviation prices."
            )
        if (grouped["downwards deviation price"].nunique(dropna=False) > 1).any():
            raise ValueError(
                "Commitment groups cannot have non-unique downwards deviation prices."
            )

        for _, sub_commitment in grouped:
            if len(sub_commitment) == 1:
                commitment_mapping[len(sub_commitments)] = c
                sub_commitments.append(sub_commitment)
            else:
                down_commitment = sub_commitment.drop(columns="upwards deviation price")
                up_commitment = sub_commitment.drop(columns="downwards deviation price")
                commitment_mapping[len(sub_commitments)] = c
                commitment_mapping[len(sub_commitments) + 1] = c
                sub_commitments.extend([down_commitment, up_commitment])
    return sub_commitments, commitment_mapping


def loss_coefficients(efficiency: float) -> tuple[float, float]:
    """Coefficients (a, b) of one step of the stock recursion, for `how="linear"`.

    stock[j] = a * stock[j-1] + b * change[j]

    Mirrors :func:`apply_stock_changes_and_losses`, which we cannot call here
    because it expects numbers, while `change[j]` may be a Pyomo expression.
    """
    if efficiency == 1:
        return 1.0, 1.0
    return efficiency, (efficiency - 1) / math.log(efficiency)


@dataclass
class SchedulingProblem:
    """Everything both scheduler backends need before building their model.

    Produced by :func:`prepare_scheduling_problem`; see ``device_scheduler``'s
    docstring for what the underlying arguments mean.
    """

    #: Timing, taken from the first device
    start: object
    end: object
    resolution: object

    #: Device constraints, with a "stock delta" column guaranteed to be present
    device_constraints: list[pd.DataFrame]

    #: EMS constraints, normalised to a list, plus the device indices each applies to
    ems_constraints_list: list[pd.DataFrame]
    ems_constraint_device_groups: list[list[int]]

    #: device -> its primary stock group key, and stock group key -> member devices
    device_to_group: dict[int, str]
    group_to_devices: dict[str, list[int]]

    #: Sub-commitments (one per commitment group and deviation direction), and the
    #: mapping from each sub-commitment index back to its original commitment index
    commitments: list[pd.DataFrame]
    commitment_mapping: dict[int, int]

    #: sub-commitment index -> {device group label -> member device indices}
    device_group_lookup: dict[int, dict]

    #: Whether the summed deviation prices describe a convex cost curve
    #: (a non-convex curve needs binary commitment-sign variables)
    convex_cost_curve: bool

    #: Big-Ms bounding the search space for device power (Md) and commitment
    #: deviations (Mc)
    Md: float
    Mc: float

    #: device index -> its signed power bands (S2 operation modes)
    band_lookup: dict[int, list[tuple[float, float]]]

    initial_stock: float | list[float]

    #: The commitments as passed in, before the sub-commitment split. Only kept to
    #: derive :attr:`commodity_devices` lazily.
    original_commitments: list[pd.DataFrame] = field(default_factory=list, repr=False)

    def initial_stock_of(self, d) -> float:
        """The initial stock of device ``d``, defaulting to 0.

        Device indices reaching this from a commitment's "device" column may be
        numpy floats, hence the cast.
        """
        if isinstance(self.initial_stock, list):
            # No initial stock defined for inflexible device
            d = int(d)
            return self.initial_stock[d] if d < len(self.initial_stock) else 0
        return self.initial_stock

    @cached_property
    def commodity_devices(self) -> dict:
        """commodity -> set(device indices).

        Computed on demand: only the EMS-level flow commitment constraints need
        it, and the per-row scan is not cheap enough to pay for unconditionally.
        """
        commodity_devices: dict = {}
        for df in self.original_commitments:
            if "commodity" not in df.columns or "device" not in df.columns:
                continue

            for _, row in df[["commodity", "device"]].dropna().iterrows():
                devices = row["device"]
                if not isinstance(devices, (list, tuple, set)):
                    devices = [devices]

                commodity_devices.setdefault(row["commodity"], set()).update(devices)
        return commodity_devices


def prepare_scheduling_problem(  # noqa C901
    device_constraints: list[pd.DataFrame],
    ems_constraints: pd.DataFrame | list[pd.DataFrame],
    commitment_quantities: list[pd.Series] | None = None,
    commitment_downwards_deviation_price: list[pd.Series] | list[float] | None = None,
    commitment_upwards_deviation_price: list[pd.Series] | list[float] | None = None,
    commitments: list[pd.DataFrame] | list[Commitment] | None = None,
    initial_stock: float | list[float] = 0,
    stock_groups: dict[int, list[int]] | None = None,
    ems_constraint_groups: list[list[int]] | None = None,
    device_power_bands: list[list[tuple[float, float]] | None] | None = None,
) -> SchedulingProblem:
    """Normalise and validate ``device_scheduler``'s arguments into a SchedulingProblem.

    .. note:: This adds a "stock delta" column to the passed ``device_constraints``
        DataFrames in place, as the schedulers have always done.
    """
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

    # Group keys are namespaced strings: a declared stock group's key (a state-of-charge
    # sensor id) could otherwise collide with the device index of an ungrouped device,
    # silently merging that device into the stock group.
    if stock_groups:
        for g, devices in stock_groups.items():
            for d in devices:
                device_to_group[d] = f"stock:{g}"
    # Devices not in any stock group (e.g. inflexible devices) form individual groups.
    for d in range(len(device_constraints)):
        if d not in device_to_group:
            device_to_group[d] = f"device:{d}"

    group_to_devices: dict[str, list[int]] = {}
    for d, g in device_to_group.items():
        group_to_devices.setdefault(g, []).append(d)

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

    original_commitments = list(commitments)
    commitments, commitment_mapping = convert_commitments_to_subcommitments(commitments)

    device_group_lookup: dict[int, dict] = {}

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
    if commitments:
        df = pd.concat(commitments)[
            ["upwards deviation price", "downwards deviation price"]
        ]
        df = df.groupby(level=0).sum()
        convex_cost_curve = (
            len(df[df["upwards deviation price"] < df["downwards deviation price"]])
            == 0
        )
    else:
        # No commitments at all: nothing can make the cost curve non-convex.
        # (The Pyomo path used to raise on the empty pd.concat here.)
        convex_cost_curve = True

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

    # Look up power bands (S2 operation modes) per device
    if device_power_bands is None:
        device_power_bands = [None] * len(device_constraints)
    elif len(device_power_bands) != len(device_constraints):
        raise ValueError(
            f"device_power_bands lists {len(device_power_bands)} devices, "
            f"while device_constraints lists {len(device_constraints)} devices."
        )
    band_lookup: dict[int, list[tuple[float, float]]] = {
        d: list(bands)
        for d, bands in enumerate(device_power_bands)
        if bands is not None and len(bands) > 0
    }
    for d, bands in band_lookup.items():
        for band in bands:
            if len(band) != 2 or band[0] > band[1]:
                raise ValueError(
                    f"Invalid power band {band} for device {d}: "
                    f"expected a (min, max) pair with min <= max."
                )

    return SchedulingProblem(
        start=start,
        end=end,
        resolution=resolution,
        device_constraints=device_constraints,
        ems_constraints_list=ems_constraints_list,
        ems_constraint_device_groups=ems_constraint_device_groups,
        device_to_group=device_to_group,
        group_to_devices=group_to_devices,
        commitments=commitments,
        commitment_mapping=commitment_mapping,
        device_group_lookup=device_group_lookup,
        convex_cost_curve=convex_cost_curve,
        Md=Md,
        Mc=Mc,
        band_lookup=band_lookup,
        initial_stock=initial_stock,
        original_commitments=original_commitments,
    )


def aggregate_subcommitment_costs(
    subcommitment_costs: dict, commitment_mapping: dict
) -> dict:
    """Sum sub-commitment costs back onto the commitments they were split from."""
    commitment_costs: dict = {}
    for g, v in subcommitment_costs.items():
        c = commitment_mapping[g]
        commitment_costs[c] = commitment_costs.get(c, 0) + v
    return commitment_costs


def aggregate_commodity_costs(
    commitments: list[pd.DataFrame], subcommitment_costs: dict
) -> dict:
    """Sum sub-commitment costs per commodity, skipping commitments without one."""
    commodity_costs: dict = {}
    for c in range(len(commitments)):
        commodity = None
        if "commodity" in commitments[c].columns:
            commodity = commitments[c]["commodity"].iloc[0]
        if commodity is None or (isinstance(commodity, float) and np.isnan(commodity)):
            continue
        commodity_costs[commodity] = (
            commodity_costs.get(commodity, 0) + subcommitment_costs[c]
        )
    return commodity_costs


def planned_power_per_device(
    power_per_device, start, end, resolution
) -> list[pd.Series]:
    """Turn each device's planned power values into a time series."""
    return [
        initialize_series(
            data=list(values),
            start=start,
            end=end,
            resolution=to_offset(resolution),
        )
        for values in power_per_device
    ]
