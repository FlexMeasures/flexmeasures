"""Solver-agnostic preparation of the device scheduler's inputs.

:func:`flexmeasures.data.models.planning.linear_optimization.device_scheduler` (Pyomo) and
:func:`flexmeasures.data.models.planning.highspy_optimization.device_scheduler_highspy` (direct HiGHS)
build the same mathematical model in two very different representations,
so the model construction itself is necessarily written twice.
Everything *around* it is not:
normalising arguments, resolving stock groups, converting legacy commitments, deriving Big-Ms,
and turning solver output back into schedules and costs is plain pandas/numpy work with no solver in it.

Keeping that work here means the two backends cannot drift apart on input handling —
only on the model, which is what the equivalence tests in ``tests/test_highspy_equivalence.py`` compare.
It also gives both backends a single place to grow support for a new scheduling feature's *inputs*.
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

    Pyomo's appsi_highs interface applies solver options without checking HiGHS' return status,
    so an unknown name, an invalid value, or a feature missing from the installed HiGHS build is otherwise ignored without a word.
    That silently turns a mis-typed option into a no-op, and a benchmark of it into a false negative.
    Probing a throwaway Highs instance surfaces the rejection instead.
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

    HiGHS (whether reached through Pyomo as ``appsi_highs`` or directly as ``highspy`` -- both match on "highs")
    gets a tight-tolerance profile,
    so the two backends cannot disagree on tolerances and silently produce different schedules.
    Operator-configured options are applied last, so they win.
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
    making it possible that deviations/breaches can be accounted for properly within this group (e.g. highest breach per calendar month defines the penalty).
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

        # Group rows by the "group" column in order of first appearance (like pd.unique),
        # in a single pass rather than by filtering the DataFrame once per group
        # (which would scale quadratically with the number of time steps, as each time step often forms its own group).
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


def deviation_price(commitment: pd.DataFrame, column: str) -> float:
    """The single deviation price that the optimizers apply to a commitment, for the given price column.

    A commitment carries one pair of deviation variables, priced by one pair of prices,
    so the price in its first row stands for the whole commitment.
    ``convert_commitments_to_subcommitments`` guarantees that is well defined, by rejecting a group whose prices differ per row.
    A missing column, or a missing price, means no price at all.
    """
    if column not in commitment.columns:
        return 0.0
    price = commitment[column].iloc[0]
    if pd.isna(price):
        return 0.0
    return float(price)


PRICE_COLUMNS = ("upwards deviation price", "downwards deviation price")


def _subcommitment_shape(commitment: pd.DataFrame, scope: dict) -> tuple:
    """What makes two sub-commitments impose the identical constraint.

    A sub-commitment contributes ``quantity[j] + downwards + upwards - (the scoped flow at j)``, bounded below by zero where it carries an upwards price and above by zero where it carries a downwards price.
    So two sub-commitments constrain the solver identically when they agree on all of: which prices they carry (that is what sets the bounds), what they bind (flow or stock, and for a stock which stock), the devices they are scoped to, and their quantity at every time step they cover.
    They may still differ in the *level* of those prices, which is the whole point: that is what distinguishes the commitments while leaving their constraints interchangeable.
    The commodity is part of the shape too, since costs are reported per commodity off the sub-commitment that carried them.
    """
    quantities = tuple(
        (int(j), None if pd.isna(q) else float(q))
        for j, q in zip(commitment["j"], commitment["quantity"])
    )
    stock = None
    if "stock" in commitment.columns and pd.notna(commitment["stock"].iloc[0]):
        stock = int(commitment["stock"].iloc[0])
    commodity = None
    if "commodity" in commitment.columns and not _is_missing(
        commitment["commodity"].iloc[0]
    ):
        commodity = commitment["commodity"].iloc[0]
    return (
        commitment["class"].iloc[0],
        tuple(column for column in PRICE_COLUMNS if column in commitment.columns),
        stock,
        commodity,
        quantities,
        frozenset(
            (label, frozenset(devices))
            for label, devices in sorted(scope.items(), key=repr)
        ),
    )


def interchangeable_subcommitments(
    commitments: list[pd.DataFrame], device_group_lookup: dict[int, dict]
) -> list[list[int]]:
    """Sub-commitments that impose the identical constraint, grouped, singletons dropped.

    Such sub-commitments pin the same deviation in any bounded solution, because their constraints say the same thing,
    so one of them can carry the group: the duplicates add a variable pair and a constraint row each without adding any information.
    Replacing a group by one sub-commitment carrying the summed prices is what lets a commitment that is not convex on its own be priced
    against a partner that more than compensates, since there is then one deviation to inflate rather than one each (GH#2534).
    """
    groups: dict[tuple, list[int]] = {}
    for c, commitment in enumerate(commitments):
        shape = _subcommitment_shape(commitment, device_group_lookup.get(c, {}))
        groups.setdefault(shape, []).append(c)
    return [members for members in groups.values() if len(members) > 1]


def merge_interchangeable_subcommitments(
    commitments: list[pd.DataFrame],
    commitment_mapping: dict[int, int],
    device_group_lookup: dict[int, dict],
    worth_merging,
) -> tuple[list[pd.DataFrame], dict[int, int], dict[int, dict], dict[int, list[tuple]]]:
    """Replace each group of interchangeable sub-commitments that ``worth_merging`` selects by one carrying their summed prices.

    The duplicates say nothing the first one does not, so the merged sub-commitment constrains the solver exactly as the group did,
    with one pair of deviation variables and one constraint row in place of one each.
    What the group's members do *not* share is the level of their prices, so the merged sub-commitment is priced on their sum,
    and each member's own prices are recorded against it so that its share of the cost can be worked out again after the solve.

    :param worth_merging: called with a group's member indices; a group it rejects is left alone, so a problem that gains nothing keeps its model unchanged.
    :returns: the sub-commitments, their mapping back to the original commitments, their device-group lookup, and, per merged index, the ``(original index, upwards price, downwards price)`` of each member.
    """
    groups = [
        members
        for members in interchangeable_subcommitments(commitments, device_group_lookup)
        if worth_merging(members)
    ]
    if not groups:
        return commitments, commitment_mapping, device_group_lookup, {}

    absorbed = {member for members in groups for member in members[1:]}
    leaders = {members[0]: members for members in groups}

    merged: list[pd.DataFrame] = []
    merged_mapping: dict[int, int] = {}
    merged_lookup: dict[int, dict] = {}
    merged_constituents: dict[int, list[tuple]] = {}
    for c, commitment in enumerate(commitments):
        if c in absorbed:
            continue
        new_index = len(merged)
        members = leaders.get(c)
        if members is None:
            merged.append(commitment)
        else:
            combined = commitment.copy()
            for column in PRICE_COLUMNS:
                if column in combined.columns:
                    combined[column] = sum(
                        deviation_price(commitments[member], column)
                        for member in members
                    )
            merged.append(combined)
            merged_constituents[new_index] = [
                (
                    commitment_mapping[member],
                    deviation_price(commitments[member], PRICE_COLUMNS[0]),
                    deviation_price(commitments[member], PRICE_COLUMNS[1]),
                )
                for member in members
            ]
        merged_mapping[new_index] = commitment_mapping[c]
        merged_lookup[new_index] = device_group_lookup.get(c, {})
    return merged, merged_mapping, merged_lookup, merged_constituents


def _is_missing(value) -> bool:
    """Whether ``value`` is missing, in the sense ``DataFrame.dropna`` uses.

    A commitment's "device" column may hold a collection of device indices, which ``pd.isna`` would answer element-wise;
    such a value is never missing.
    """
    if isinstance(value, (list, tuple, set, np.ndarray)):
        return False
    return bool(pd.isna(value))


def loss_coefficients(efficiency: float) -> tuple[float, float]:
    """Coefficients (a, b) of one step of the stock recursion, for `how="linear"`.

    stock[j] = a * stock[j-1] + b * change[j]

    Mirrors :func:`apply_stock_changes_and_losses`, which we cannot call here because it expects numbers,
    while `change[j]` may be a Pyomo expression.
    """
    if efficiency == 1:
        return 1.0, 1.0
    return efficiency, (efficiency - 1) / math.log(efficiency)


@dataclass
class SchedulingProblem:
    """Everything both scheduler backends need before building their model.

    Produced by :func:`prepare_scheduling_problem`;
    see ``device_scheduler``'s docstring for what the underlying arguments mean.
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

    #: Per merged sub-commitment index, the ``(original index, upwards price, downwards price)`` of each
    #: commitment merged into it, so that its share of the realised cost can be worked out again.
    merged_constituents: dict[int, list[tuple]]

    #: Whether every commitment's deviation prices describe a convex cost curve
    #: (a non-convex curve needs binary commitment-sign variables).
    #: A merged sub-commitment is judged on the summed prices it carries, which is the point of merging it.
    convex_cost_curve: bool

    #: Big-Ms bounding the search space for device power (Md) and commitment deviations (Mc)
    Md: float
    Mc: float

    #: device index -> its signed power bands (S2 operation modes)
    band_lookup: dict[int, list[tuple[float, float]]]

    #: (group index, device index, coefficient) triples for hard flow-coupling constraints
    coupling_device_specs: list[tuple[int, int, float]]

    #: device lists of the balance groups (internal commodity nodes), empty groups dropped
    balance_group_specs: list[list[int]]

    initial_stock: float | list[float]

    #: The commitments as passed in, before the sub-commitment split.
    #: Only kept to derive :attr:`commodity_devices` lazily.
    original_commitments: list[pd.DataFrame] = field(default_factory=list, repr=False)

    def initial_stock_of(self, d) -> float:
        """The initial stock of device ``d``, defaulting to 0.

        Device indices reaching this from a commitment's "device" column may be numpy floats, hence the cast.
        """
        if isinstance(self.initial_stock, list):
            # No initial stock defined for inflexible device
            d = int(d)
            return self.initial_stock[d] if d < len(self.initial_stock) else 0
        return self.initial_stock

    @cached_property
    def commodity_devices(self) -> dict:
        """commodity -> set(device indices).

        Computed on demand: only the EMS-level flow commitment constraints need it,
        and the per-row scan is not cheap enough to pay for unconditionally.
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
    coupling_groups: dict[str, list[tuple[int, float]]] | None = None,
    balance_groups: dict[str, list[int]] | None = None,
) -> SchedulingProblem:
    """Normalise and validate ``device_scheduler``'s arguments into a SchedulingProblem.

    .. note:: This adds a "stock delta" column to the passed ``device_constraints`` DataFrames in place,
        as the schedulers have always done.
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
    group_to_devices: dict[str, list[int]] = {}

    # Group keys are namespaced strings: a declared stock group's key (a state-of-charge sensor id)
    # could otherwise collide with the device index of an ungrouped device,
    # silently merging that device into the stock group.
    #
    # A device may belong to more than one stock group —
    # a commodity converter (e.g. a steamer bridging a heat node and a steam node) participates in every node it touches,
    # so ``group_to_devices`` keeps the full (possibly overlapping) membership.
    # ``device_to_group`` records only the primary group (first assignment wins),
    # used where a single owning group is needed (per-device stock bounds).
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
    # Each device in each group will be constrained: P[d, j] == coeff * alpha[group, j],
    # where alpha is a free variable representing the common normalised flow.
    coupling_device_specs: list[tuple[int, int, float]] = []
    if coupling_groups:
        for g_idx, (_group_name, members) in enumerate(coupling_groups.items()):
            for d_idx, coeff in members:
                coupling_device_specs.append((g_idx, d_idx, coeff))

    # Collect the device lists of the balance groups (internal commodity nodes).
    balance_group_specs: list[list[int]] = []
    if balance_groups:
        balance_group_specs = [
            list(devices) for devices in balance_groups.values() if devices
        ]

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

        # Read the columns as arrays rather than slicing + dropna()-ing a fresh DataFrame per sub-commitment.
        # Each time step usually forms its own group, so this loop runs once per time step,
        # and the per-call pandas overhead dominated it
        # (~50 ms of a ~135 ms prepare on 4 devices x 192 steps; the arrays bring that under 1 ms).
        device_values = df["device"].to_numpy()
        if has_device_group:
            group_values = df["device_group"].to_numpy()
        else:
            # Backwards-compatible default: each device is its own group.
            # This preserves the behaviour of old-style DataFrame commitments that
            # pre-date the device_group feature (e.g. from initialize_device_commitment).
            group_values = device_values

        groups: dict = {}
        for d, g in zip(device_values, group_values):
            # Skip what the previous dropna() dropped:
            # a missing device, or a missing group label when the commitment declares groups.
            if _is_missing(d) or (has_device_group and _is_missing(g)):
                continue

            if isinstance(d, (list, tuple, set, np.ndarray)):
                devices = set(d)
            else:
                devices = {d}

            groups.setdefault(g, set()).update(devices)

        device_group_lookup[c] = groups

    # Each commitment carries its own pair of deviation variables, priced by its own pair of prices,
    # so a convex cost curve is a property of one commitment at a time:
    # deviating upwards has to cost at least what deviating downwards pays.
    # Summing the prices of every commitment per time step instead would let one commitment's prices mask another's non-convexity,
    # which leaves out the commitment-sign variables that keep such a commitment bounded (GH#2534).
    def _is_convex(commitment: pd.DataFrame) -> bool:
        """Deviating upwards costs at least what deviating downwards pays."""
        return deviation_price(
            commitment, "upwards deviation price"
        ) >= deviation_price(commitment, "downwards deviation price")

    def _worth_merging(members: list[int]) -> bool:
        """Whether merging this group of interchangeable sub-commitments saves the sign variables.

        A group that is already convex throughout needs none to begin with, so merging it would change a model for nothing.
        A group whose summed prices are still not convex needs them either way, and merging it would only hide which member asked for them.
        What is left is the group this is for: one that is not convex member by member, and is once its prices are added up.
        """
        if all(_is_convex(commitments[member]) for member in members):
            return False
        summed = {
            column: sum(
                deviation_price(commitments[member], column) for member in members
            )
            for column in PRICE_COLUMNS
        }
        return summed["upwards deviation price"] >= summed["downwards deviation price"]

    # Sub-commitments whose constraints are interchangeable say the same thing, so one of them can carry the group,
    # priced on their summed prices. That leaves one deviation to inflate rather than one each,
    # which is what lets a commitment that is not convex on its own be carried by a partner that more than compensates,
    # and it drops the duplicates' variables and rows rather than constraining them to agree (GH#2534).
    (
        commitments,
        commitment_mapping,
        device_group_lookup,
        merged_constituents,
    ) = merge_interchangeable_subcommitments(
        commitments, commitment_mapping, device_group_lookup, _worth_merging
    )

    # With no commitments at all, there is nothing to make the curve non-convex.
    # A merged sub-commitment is judged on the summed prices it now carries, which is the point of having merged it.
    convex_cost_curve = all(_is_convex(commitment) for commitment in commitments)

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

    problem = SchedulingProblem(
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
        merged_constituents=merged_constituents,
        convex_cost_curve=convex_cost_curve,
        Md=Md,
        Mc=Mc,
        band_lookup=band_lookup,
        coupling_device_specs=coupling_device_specs,
        balance_group_specs=balance_group_specs,
        initial_stock=initial_stock,
        original_commitments=original_commitments,
    )
    _validate_commitments_are_enforceable(problem)
    return problem


def _validate_commitments_are_enforceable(problem: SchedulingProblem) -> None:
    """Raise when a sub-commitment would be bound by no constraint family.

    The model only binds a commitment through its device groups (``grouped_commitment_equalities``),
    or, for a flow commitment naming no device, through the EMS-level flow constraints (``ems_flow_commitment_equalities``).
    A commitment reaching neither family leaves its deviation variables in the objective without any constraint:
    the commitment is silently dropped, or, when a deviation price has the favourable sign, the problem becomes unbounded.
    """
    for c, df in enumerate(problem.commitments):
        identity = _identify_commitment(df, problem.commitment_mapping[c])
        groups = problem.device_group_lookup.get(c)
        if groups:
            if any(groups.values()):
                continue
            raise ValueError(
                f"{identity} names only empty device groups, so no constraint would bind it."
            )

        # No device grouping: only the EMS-level flow constraints could bind it.
        if df["class"].iloc[0] != FlowCommitment:
            raise ValueError(
                f"{identity} is a stock commitment that names no device and no known stock group, so no constraint would bind it."
            )
        if "commodity" in df.columns:
            commodity = df["commodity"].iloc[0]
            if not _is_missing(commodity) and not problem.commodity_devices.get(
                commodity
            ):
                raise ValueError(
                    f"{identity} names commodity '{commodity}', but no commitment maps devices to that commodity, so no constraint would bind it."
                )


def _identify_commitment(df: pd.DataFrame, original_index: int) -> str:
    """Identify a commitment the way the user knows it: by its name, when available.

    Commitments passed as plain DataFrames carry no name column, so those fall back to the index alone.
    The name is quoted with ``repr``, which switches quote style when the name itself contains a quote.
    """
    if "name" in df.columns and not _is_missing(df["name"].iloc[0]):
        return f"Commitment {str(df['name'].iloc[0])!r} (index {original_index})"
    return f"Commitment {original_index}"


def aggregate_subcommitment_costs(
    subcommitment_costs: dict,
    commitment_mapping: dict,
    merged_constituents: dict | None = None,
    deviations: dict | None = None,
) -> dict:
    """Sum sub-commitment costs back onto the commitments they were split from.

    A merged sub-commitment stands for several commitments at once, so its realised cost is shared out by their own prices
    against the deviation they share: a commitment priced ``up_i`` and ``down_i`` carries ``u * up_i + d * down_i`` of it.
    That is exact rather than apportioned, because the deviation is one and the same for every commitment merged into it,
    which is why merging them costs nothing in what can be reported afterwards.

    Costs come back ordered by commitment, since callers read them off alongside the commitments themselves.

    :param deviations: per sub-commitment index, its realised ``(upwards, downwards)`` deviation, signed as the solver holds them.
    """
    commitment_costs: dict = {}
    merged_constituents = merged_constituents or {}
    deviations = deviations or {}
    for g, v in subcommitment_costs.items():
        constituents = merged_constituents.get(g)
        if constituents is None:
            c = commitment_mapping[g]
            commitment_costs[c] = commitment_costs.get(c, 0) + v
            continue
        upwards, downwards = deviations.get(g, (0.0, 0.0))
        for c, up_price, down_price in constituents:
            commitment_costs[c] = (
                commitment_costs.get(c, 0) + upwards * up_price + downwards * down_price
            )
    return dict(sorted(commitment_costs.items()))


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
