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

import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import cached_property
from typing import TypedDict

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
        # HiGHS writes its log straight to the console, bypassing our loggers,
        # so only let it through when debugging.
        # The app logger's level reflects LOGGING_LEVEL, whether that was configured as a name (e.g. "INFO") or a number (e.g. logging.INFO).
        if current_app.logger.getEffectiveLevel() > logging.DEBUG:
            profile["output_flag"] = "false"

    configured_options = current_app.config.get("FLEXMEASURES_LP_SOLVER_OPTIONS") or {}
    if configured_options and is_highs:
        validate_highs_options(configured_options)
    profile.update(configured_options)
    return profile


PRICE_COLUMNS = ("upwards deviation price", "downwards deviation price")

#: What the model builders read of one sub-commitment, gathered once rather than read back off its frame.
#: :func:`convert_commitments_to_subcommitments` gathers these while splitting,
#: and :func:`_header_from_frame` takes the same keys from a sub-commitment frame.
#: A missing column and a missing value both come back as ``None``.
#: The keys are spelled as the commitment columns they come from, hence the functional syntax.
SubCommitmentHeader = TypedDict(
    "SubCommitmentHeader",
    {
        # The commitment's name and class (FlowCommitment or StockCommitment), constant down the commitment.
        "name": object,
        "class": type,
        # The commodity of the sub-commitment's first row.
        # A commitment may map its devices to different commodities, so this can differ between the sub-commitments of one commitment.
        "commodity": object,
        # The stock group a stock commitment binds.
        "stock": object,
        # The device (or collection of devices) in each row, or None for an EMS-level commitment.
        "device": "np.ndarray | None",
        # The device group label in each row, or None when the commitment declares no device groups, which "has_device_group" tells.
        "device_group": "np.ndarray | None",
        "has_device_group": bool,
        # The deviation prices this sub-commitment carries: each half of a two-sided group carries only its own direction's price.
        "upwards deviation price": object,
        "downwards deviation price": object,
        # Which of PRICE_COLUMNS the sub-commitment carries, which is what sets its row bounds.
        "price columns": "tuple[str, ...]",
        # Every row, as (time step indices, quantities).
        "rows": "tuple[np.ndarray, np.ndarray]",
        # The rows a model builder binds, as (quantities, time step indices, lb, ub).
        # A NaN or -inf quantity deactivates the commitment at that time step, the way the Pyomo Param's -inf does.
        "active rows": "tuple[np.ndarray, np.ndarray, float, float]",
    },
)


def _row_bounds(price_columns: tuple[str, ...]) -> tuple[float, float]:
    """The bounds on a sub-commitment's rows: lb is 0 iff it prices upwards deviations, and ub is 0 iff it prices downwards deviations."""
    lb = 0.0 if "upwards deviation price" in price_columns else -infinity
    ub = 0.0 if "downwards deviation price" in price_columns else infinity
    return lb, ub


def _active_rows(
    j_values: np.ndarray, quantity_values: np.ndarray, price_columns: tuple[str, ...]
) -> tuple[np.ndarray, np.ndarray, float, float]:
    """The ``"active rows"`` of a :data:`SubCommitmentHeader`: those whose quantity is neither NaN nor -inf, with the row bounds."""
    active = ~(np.isnan(quantity_values) | (quantity_values == -infinity))
    return (quantity_values[active], j_values[active], *_row_bounds(price_columns))


def _first_value(values: np.ndarray | None, positions: np.ndarray) -> object:
    """The value at a group's first row, or None when the column is absent or the value is missing."""
    if values is None:
        return None
    value = values[positions[0]]
    return None if _is_missing(value) else value


class SubCommitmentFrames(Sequence):
    """The sub-commitment frames, each built the first time it is asked for.

    Splitting a commitment produces one sub-commitment per group,
    and a group is usually a single time step,
    so a schedule can hold thousands of one-row frames.
    The HiGHS backend works entirely from the headers gathered during the split and never looks at them;
    the Pyomo backend uses them throughout.
    Building them all up front therefore cost more than the rest of the split put together,
    and for the default backend it bought nothing.

    Each entry knows the frame it came from, the row positions of its group,
    the price column its half of a two-sided group drops,
    and, for a sub-commitment that carries a merged group (see :func:`merge_interchangeable_subcommitments`),
    the prices it carries in place of its own.
    """

    def __init__(self, specs: list[tuple]):
        self._specs = specs
        self._frames: dict[int, pd.DataFrame] = {}

    def __len__(self) -> int:
        return len(self._specs)

    def __getitem__(self, index):
        if isinstance(index, slice):
            return [self[i] for i in range(*index.indices(len(self)))]
        frame = self._frames.get(index)
        if frame is None:
            source, positions, dropped_column, *rest = self._specs[index]
            frame = source.iloc[positions]
            if dropped_column is not None:
                frame = frame.drop(columns=dropped_column)
            prices = rest[0] if rest else None
            if prices:
                frame = frame.copy()
                for column, price in prices.items():
                    if column in frame.columns:
                        frame[column] = price
            self._frames[index] = frame
        return frame

    def select(self, kept: list[int], prices: dict[int, dict]) -> SubCommitmentFrames:
        """The sub-commitments at ``kept``, in that order, with ``prices`` set on those (by new index) that carry a merged group."""
        return SubCommitmentFrames(
            [
                (*self._specs[c][:3], prices.get(new_index))
                for new_index, c in enumerate(kept)
            ]
        )


def convert_commitments_to_subcommitments(
    dfs: list[pd.DataFrame],
) -> tuple[SubCommitmentFrames, dict[int, int], list[SubCommitmentHeader]]:
    """Transform commitments, each specifying a group for each time step, to sub-commitments, one per group.

    'Groups' are a commitment concept (grouping time slots of a commitment),
    making it possible that deviations/breaches can be accounted for properly within this group (e.g. highest breach per calendar month defines the penalty).
    Here, we define sub-commitments, by separating commitments by group and by direction of deviation (up, down).

    We also enumerate the time steps in a new column "j".

    For example, given contracts A and B (represented by 2 DataFrames), each with 3 groups,
    we return (sub)commitments A1, A2, A3, B1, B2 and B3,
    where A,B,C is the enumerated contract and 1,2,3 is the enumerated group.

    Along with the sub-commitments, we return each one's :data:`SubCommitmentHeader`.
    """
    commitment_mapping = {}
    sub_commitments = []
    # The headers, gathered here rather than read back from every sub-commitment:
    # a commitment is split into one sub-commitment per group, and each time step is often its own group,
    # so reading them afterwards costs a frame lookup per time step per commitment instead of one per commitment.
    headers: list[SubCommitmentHeader] = []
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
        group_column = df["group"]
        grouped = df.drop(columns=["group"]).groupby(group_column, sort=False)

        # Catch non-uniqueness (vectorized across all groups)
        if (grouped["upwards deviation price"].nunique(dropna=False) > 1).any():
            raise ValueError(
                "Commitment groups cannot have non-unique upwards deviation prices."
            )
        if (grouped["downwards deviation price"].nunique(dropna=False) > 1).any():
            raise ValueError(
                "Commitment groups cannot have non-unique downwards deviation prices."
            )

        # Constant down the whole commitment, so read once here.
        # The commodity is not: a commitment may map its devices to different commodities, so it is read per group below.
        shared = {
            column: (
                None
                if df.empty
                or column not in df.columns
                or _is_missing(df[column].iloc[0])
                else df[column].iloc[0]
            )
            for column in ("name", "class", "stock")
        }
        shared["class"] = shared["class"] or FlowCommitment
        # Prices are constant within a group (checked just above),
        # so one vectorized aggregation gives every group's price at once.
        up_by_group = grouped["upwards deviation price"].first()
        down_by_group = grouped["downwards deviation price"].first()

        # The columns read per group, read once per commitment and sliced per group below,
        # rather than read back off every sub-commitment.
        commodity_values = (
            df["commodity"].to_numpy() if "commodity" in df.columns else None
        )
        device_values = df["device"].to_numpy() if "device" in df.columns else None
        device_group_values = (
            df["device_group"].to_numpy() if "device_group" in df.columns else None
        )
        quantity_values = df["quantity"].to_numpy(dtype=float)
        j_values = df["j"].to_numpy(dtype=np.int64)
        group_positions = grouped.indices

        # The frame the groupby would have handed out, minus the column it grouped on.
        without_group = df.drop(columns=["group"])

        for group_key in pd.unique(group_column):
            positions = group_positions[group_key]
            up_price = up_by_group.get(group_key)
            down_price = down_by_group.get(group_key)
            group_header = {
                **shared,
                "commodity": _first_value(commodity_values, positions),
                "device": (None if device_values is None else device_values[positions]),
                "device_group": (
                    None
                    if device_values is None or device_group_values is None
                    else device_group_values[positions]
                ),
                "has_device_group": device_group_values is not None,
                "upwards deviation price": None if _is_missing(up_price) else up_price,
                "downwards deviation price": (
                    None if _is_missing(down_price) else down_price
                ),
                "rows": (j_values[positions], quantity_values[positions]),
            }
            if len(positions) == 1:
                halves = [(None, PRICE_COLUMNS)]
            else:
                # Each half keeps only its own direction's price.
                halves = [
                    ("upwards deviation price", ("downwards deviation price",)),
                    ("downwards deviation price", ("upwards deviation price",)),
                ]
            for dropped_column, price_columns in halves:
                commitment_mapping[len(sub_commitments)] = c
                sub_commitments.append((without_group, positions, dropped_column))
                header = {
                    **group_header,
                    "price columns": price_columns,
                    "active rows": _active_rows(
                        j_values[positions], quantity_values[positions], price_columns
                    ),
                }
                if dropped_column is not None:
                    header[dropped_column] = None
                headers.append(header)
    return SubCommitmentFrames(sub_commitments), commitment_mapping, headers


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


def header_price(header: SubCommitmentHeader, column: str) -> float:
    """:func:`deviation_price`, read off a sub-commitment's constant columns (see :func:`convert_commitments_to_subcommitments`) rather than its frame."""
    price = header.get(column)
    if price is None or pd.isna(price):
        return 0.0
    return float(price)


def _first_row_value(commitment: pd.DataFrame, column: str) -> object:
    """The value in a sub-commitment frame's first row, or None when the column is absent or the value is missing."""
    if commitment.empty or column not in commitment.columns:
        return None
    return _first_value(commitment[column].to_numpy(), np.array([0]))


def _header_from_frame(commitment: pd.DataFrame) -> SubCommitmentHeader:
    """The :data:`SubCommitmentHeader` of a sub-commitment frame.

    :func:`convert_commitments_to_subcommitments` gathers these while splitting;
    this is for callers that hand over the frames themselves.
    """
    price_columns = tuple(
        column for column in PRICE_COLUMNS if column in commitment.columns
    )
    j_values = commitment["j"].to_numpy(dtype=np.int64)
    quantity_values = commitment["quantity"].to_numpy(dtype=float)
    has_device = "device" in commitment.columns
    has_device_group = "device_group" in commitment.columns
    return {
        "name": _first_row_value(commitment, "name"),
        "class": _first_row_value(commitment, "class") or FlowCommitment,
        "commodity": _first_row_value(commitment, "commodity"),
        "stock": _first_row_value(commitment, "stock"),
        "device": commitment["device"].to_numpy() if has_device else None,
        "device_group": (
            commitment["device_group"].to_numpy()
            if has_device and has_device_group
            else None
        ),
        "has_device_group": has_device_group,
        "upwards deviation price": _first_row_value(
            commitment, "upwards deviation price"
        ),
        "downwards deviation price": _first_row_value(
            commitment, "downwards deviation price"
        ),
        "price columns": price_columns,
        "rows": (j_values, quantity_values),
        "active rows": _active_rows(j_values, quantity_values, price_columns),
    }


def _subcommitment_shape(header: SubCommitmentHeader, scope: dict) -> tuple:
    """What makes two sub-commitments impose the identical constraint.

    A sub-commitment contributes ``quantity[j] + downwards + upwards - (the scoped flow at j)``, bounded below by zero where it carries an upwards price and above by zero where it carries a downwards price.
    So two sub-commitments constrain the solver identically when they agree on all of: which prices they carry (that is what sets the bounds), what they bind (flow or stock, and for a stock which stock), the devices they are scoped to, and their quantity at every time step they cover.
    They may still differ in the *level* of those prices, which is the whole point: that is what distinguishes the commitments while leaving their constraints interchangeable.
    The commodity is part of the shape too, since costs are reported per commodity off the sub-commitment that carried them.

    Read off the sub-commitment's constant columns and row arrays, gathered while splitting:
    a group is usually a single time step, so reading them off every one-row frame again cost a few pandas lookups per time step per commitment.
    """
    j_values, quantity_values = header["rows"]
    quantities = tuple(
        (int(j), None if np.isnan(q) else float(q))
        for j, q in zip(j_values.tolist(), quantity_values.tolist())
    )
    stock = header["stock"]
    return (
        header["class"],
        header["price columns"],
        None if stock is None else int(stock),
        header["commodity"],
        quantities,
        frozenset(
            (label, frozenset(devices))
            for label, devices in sorted(scope.items(), key=repr)
        ),
    )


def interchangeable_subcommitments(
    commitments: Sequence[pd.DataFrame],
    device_group_lookup: dict[int, dict],
    headers: list[SubCommitmentHeader] | None = None,
) -> list[list[int]]:
    """Sub-commitments that impose the identical constraint, grouped, singletons dropped.

    Such sub-commitments pin the same deviation in any bounded solution, because their constraints say the same thing,
    so one of them can carry the group: the duplicates add a variable pair and a constraint row each without adding any information.
    Replacing a group by one sub-commitment carrying the summed prices is what lets a commitment that is not convex on its own be priced
    against a partner that more than compensates, since there is then one deviation to inflate rather than one each (GH#2534).

    :param headers: the sub-commitments' constant columns, as :func:`convert_commitments_to_subcommitments` returns them;
                    read off the frames when not given.
    """
    if headers is None:
        headers = [_header_from_frame(commitment) for commitment in commitments]
    groups: dict[tuple, list[int]] = {}
    for c, header in enumerate(headers):
        shape = _subcommitment_shape(header, device_group_lookup.get(c, {}))
        groups.setdefault(shape, []).append(c)
    return [members for members in groups.values() if len(members) > 1]


def _merge_interchangeable(
    commitments: Sequence[pd.DataFrame],
    headers: list[SubCommitmentHeader],
    commitment_mapping: dict[int, int],
    device_group_lookup: dict[int, dict],
    worth_merging,
) -> tuple[
    Sequence[pd.DataFrame],
    list[SubCommitmentHeader],
    dict[int, int],
    dict[int, dict],
    dict[int, list[tuple]],
]:
    """:func:`merge_interchangeable_subcommitments`, on the sub-commitments' constant columns.

    Returns the merged headers as well, aligned with the merged sub-commitments.
    A :class:`SubCommitmentFrames` stays lazy: the sub-commitment carrying a merged group is only built, with its summed prices, when asked for.
    """
    groups = [
        members
        for members in interchangeable_subcommitments(
            commitments, device_group_lookup, headers=headers
        )
        if worth_merging(members)
    ]
    if not groups:
        return commitments, headers, commitment_mapping, device_group_lookup, {}

    absorbed = {member for members in groups for member in members[1:]}
    leaders = {members[0]: members for members in groups}

    kept: list[int] = []
    summed_prices: dict[int, dict] = {}
    merged_headers: list[SubCommitmentHeader] = []
    merged_mapping: dict[int, int] = {}
    merged_lookup: dict[int, dict] = {}
    merged_constituents: dict[int, list[tuple]] = {}
    for c, header in enumerate(headers):
        if c in absorbed:
            continue
        new_index = len(kept)
        kept.append(c)
        members = leaders.get(c)
        if members is None:
            merged_headers.append(header)
        else:
            summed = {
                column: sum(header_price(headers[member], column) for member in members)
                for column in header["price columns"]
            }
            summed_prices[new_index] = summed
            merged_headers.append({**header, **summed})
            merged_constituents[new_index] = [
                (
                    commitment_mapping[member],
                    header_price(headers[member], PRICE_COLUMNS[0]),
                    header_price(headers[member], PRICE_COLUMNS[1]),
                )
                for member in members
            ]
        merged_mapping[new_index] = commitment_mapping[c]
        merged_lookup[new_index] = device_group_lookup.get(c, {})

    if isinstance(commitments, SubCommitmentFrames):
        merged = commitments.select(kept, summed_prices)
    else:
        merged = []
        for new_index, c in enumerate(kept):
            commitment = commitments[c]
            if new_index in summed_prices:
                commitment = commitment.copy()
                for column, price in summed_prices[new_index].items():
                    commitment[column] = price
            merged.append(commitment)
    return merged, merged_headers, merged_mapping, merged_lookup, merged_constituents


def merge_interchangeable_subcommitments(
    commitments: Sequence[pd.DataFrame],
    commitment_mapping: dict[int, int],
    device_group_lookup: dict[int, dict],
    worth_merging,
) -> tuple[
    Sequence[pd.DataFrame], dict[int, int], dict[int, dict], dict[int, list[tuple]]
]:
    """Replace each group of interchangeable sub-commitments that ``worth_merging`` selects by one carrying their summed prices.

    The duplicates say nothing the first one does not, so the merged sub-commitment constrains the solver exactly as the group did,
    with one pair of deviation variables and one constraint row in place of one each.
    What the group's members do *not* share is the level of their prices, so the merged sub-commitment is priced on their sum,
    and each member's own prices are recorded against it so that its share of the cost can be worked out again after the solve.

    :param worth_merging: called with a group's member indices; a group it rejects is left alone, so a problem that gains nothing keeps its model unchanged.
    :returns: the sub-commitments, their mapping back to the original commitments, their device-group lookup, and, per merged index, the ``(original index, upwards price, downwards price)`` of each member.
    """
    headers = [_header_from_frame(commitment) for commitment in commitments]
    (
        merged,
        _,
        merged_mapping,
        merged_lookup,
        merged_constituents,
    ) = _merge_interchangeable(
        commitments,
        headers,
        commitment_mapping,
        device_group_lookup,
        worth_merging,
    )
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
    commitments: Sequence[pd.DataFrame]
    commitment_mapping: dict[int, int]

    #: Each sub-commitment's header, gathered while splitting, which the model builders read instead of its frame.
    commitment_headers: list[SubCommitmentHeader]

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
    (
        commitments,
        commitment_mapping,
        commitment_headers,
    ) = convert_commitments_to_subcommitments(commitments)

    device_group_lookup: dict[int, dict] = {}

    # The device/device_group/stock values come from commitment_headers, sliced from each commitment while it was split.
    # Reading them back off the sub-commitment frames meant several pandas lookups per group, and a group is usually one time step.
    for c, header in enumerate(commitment_headers):
        # Stock-scoped commitments couple to their stock group as a whole, regardless
        # of which device index they name: the group's first device carries the group's
        # stock, so a single-member group suffices (also avoiding double-counting the
        # shared stock when the commitment names multiple members).
        if header["stock"] is not None:
            stock_group_key = f"stock:{int(header['stock'])}"
            if stock_group_key in group_to_devices:
                device_group_lookup[c] = {
                    stock_group_key: {group_to_devices[stock_group_key][0]}
                }
                continue

        device_values = header["device"]
        if device_values is None:
            # EMS-level commitment: no device grouping needed here;
            # handled by ems_flow_commitment_equalities.
            continue

        has_device_group = header["has_device_group"]
        if has_device_group:
            group_values = header["device_group"]
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
    # The prices come from the constant columns gathered while splitting, not from the one-row frames, of which there is usually one per time step.
    def _is_convex(header: SubCommitmentHeader) -> bool:
        """Deviating upwards costs at least what deviating downwards pays."""
        return header_price(header, "upwards deviation price") >= header_price(
            header, "downwards deviation price"
        )

    split_headers = commitment_headers

    def _worth_merging(members: list[int]) -> bool:
        """Whether merging this group of interchangeable sub-commitments saves the sign variables.

        A group that is already convex throughout needs none to begin with, so merging it would change a model for nothing.
        A group whose summed prices are still not convex needs them either way, and merging it would only hide which member asked for them.
        What is left is the group this is for: one that is not convex member by member, and is once its prices are added up.
        """
        if all(_is_convex(split_headers[member]) for member in members):
            return False
        summed = {
            column: sum(
                header_price(split_headers[member], column) for member in members
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
        commitment_headers,
        commitment_mapping,
        device_group_lookup,
        merged_constituents,
    ) = _merge_interchangeable(
        commitments,
        commitment_headers,
        commitment_mapping,
        device_group_lookup,
        _worth_merging,
    )

    # With no commitments at all, there is nothing to make the curve non-convex.
    # A merged sub-commitment is judged on the summed prices it now carries, which is the point of having merged it.
    convex_cost_curve = all(_is_convex(header) for header in commitment_headers)

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
        commitment_headers=commitment_headers,
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
    for c, header in enumerate(problem.commitment_headers):
        groups = problem.device_group_lookup.get(c)
        if groups:
            if any(groups.values()):
                continue
            raise ValueError(
                f"{_identify_commitment(header, problem.commitment_mapping[c])}"
                " names only empty device groups, so no constraint would bind it."
            )

        identity = _identify_commitment(header, problem.commitment_mapping[c])
        # No device grouping: only the EMS-level flow constraints could bind it.
        if header["class"] != FlowCommitment:
            raise ValueError(
                f"{identity} is a stock commitment that names no device and no known stock group, so no constraint would bind it."
            )
        commodity = header["commodity"]
        if commodity is not None and not problem.commodity_devices.get(commodity):
            raise ValueError(
                f"{identity} names commodity '{commodity}', but no commitment maps devices to that commodity, so no constraint would bind it."
            )


def _identify_commitment(header: SubCommitmentHeader, original_index: int) -> str:
    """Identify a commitment the way the user knows it: by its name, when available.

    Takes the sub-commitment's :data:`SubCommitmentHeader`.
    Commitments passed as plain DataFrames carry no name column, so those fall back to the index alone.
    The name is quoted with ``repr``, which switches quote style when the name itself contains a quote.
    """
    name = header.get("name")
    if name is not None:
        return f"Commitment {str(name)!r} (index {original_index})"
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
    commitments: Sequence[pd.DataFrame] | list[SubCommitmentHeader],
    subcommitment_costs: dict,
) -> dict:
    """Sum sub-commitment costs per commodity, skipping commitments without one.

    Accepts either the sub-commitment frames or their :data:`SubCommitmentHeader`;
    the latter avoids re-indexing every frame.
    """
    commodity_costs: dict = {}
    for c, commitment in enumerate(commitments):
        commodity = (
            commitment["commodity"]
            if isinstance(commitment, dict)
            else _first_row_value(commitment, "commodity")
        )
        if commodity is None:
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
