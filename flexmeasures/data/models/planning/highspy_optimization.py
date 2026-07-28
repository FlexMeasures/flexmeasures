"""Direct HiGHS (highspy) implementation of the device scheduler.

.. warning:: TWO MODELS TO KEEP IN SYNC

    This module deliberately duplicates the mathematical model of
    :func:`flexmeasures.data.models.planning.linear_optimization.device_scheduler`
    (the Pyomo implementation), building the LP/MILP directly with the HiGHS
    Python API (``highspy``) instead. The Pyomo implementation is the semantic
    reference: any change to the variables, constraints or objective in
    ``device_scheduler`` MUST be mirrored here (and vice versa), and the
    equivalence tests in ``tests/test_highspy_equivalence.py`` should be
    extended accordingly. This trade-off (a second model to maintain) was
    accepted because bypassing the Pyomo layer cuts roughly a second (single
    device) to several seconds (multiple devices) of model construction and
    solution-ingestion overhead per scheduling job, while the direct build
    takes milliseconds.

Deviations from the Pyomo implementation (all verified against the behavior of
the ``appsi_highs`` path):

- ``ems_flow_commitment_equalities`` is not built. On the Pyomo path this
  constraint family returns ``(None, expr, None)``, i.e. a constraint without
  bounds, which ends up as a free (vacuous) row in HiGHS. We skip building the
  free rows altogether.
- Rows whose computed bounds are impossible to satisfy for any finite value
  (upper bound of -inf, or lower bound of +inf, as happens when a commitment
  quantity is +/-inf) are skipped. On the Pyomo path such rows are rejected by
  HiGHS' ``addRow`` (called by appsi) and thereby silently dropped, with the
  same net effect.
- Solver results and model objects are lightweight shims (see
  :class:`HighspySolverResults` and :class:`HighspyModel`) that expose the
  attributes callers actually consume, rather than Pyomo objects.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from flask import current_app
from pandas.tseries.frequencies import to_offset

from flexmeasures.data.models.planning import (
    Commitment,
    StockCommitment,
)
from flexmeasures.data.models.planning.utils import initialize_series

infinity = float("inf")


class _SolverStanza:
    """Mimics the ``solver`` entry of a Pyomo ``SolverResults`` object."""

    def __init__(self, termination_condition: str, status: str):
        #: str containing "optimal", "infeasible", etc. (mirrors Pyomo's
        #: str-valued TerminationCondition enum, which supports both
        #: ``== "optimal"`` and ``"infeasible" in ...`` checks)
        self.termination_condition = termination_condition
        self.status = status


class HighspySolverResults:
    """Small stand-in for Pyomo's ``SolverResults``.

    Callers only consume ``results.solver.termination_condition`` (a string
    containing "optimal"/"infeasible") and ``results.solver.status``.
    """

    def __init__(self, termination_condition: str, status: str):
        self.solver = _SolverStanza(termination_condition, status)


class _IndexedVarView:
    """Read-only stand-in for an indexed Pyomo ``Var``.

    Supports the access patterns used by callers and tests:
    ``var[d, j].value`` and ``var.extract_values()``.
    """

    class _Value:
        __slots__ = ("value",)

        def __init__(self, value):
            self.value = value

    def __init__(self, values: dict):
        self._values = values

    def __getitem__(self, key):
        return self._Value(self._values[key])

    def extract_values(self) -> dict:
        return dict(self._values)


class HighspyModel:
    """Small stand-in for the Pyomo ``ConcreteModel`` returned by ``device_scheduler``.

    Exposes the attributes that callers and tests consume:

    - ``commitment_costs``: dict of realized costs per (original) commitment
    - ``commodity_costs``: dict of realized costs per commodity
    - ``costs``: the objective value (a float; ``pyomo.environ.value()`` passes
      floats through unchanged, so ``value(model.costs)`` keeps working)
    - ``d`` and ``j``: the device and datetime index ranges
    - ``ems_power``, ``device_power_up``, ``device_power_down``,
      ``device_power_sign``: indexed variable views supporting
      ``var[d, j].value`` and ``var.extract_values()``
    """

    def __init__(self):
        self.commitment_costs: dict = {}
        self.commodity_costs: dict = {}
        self.costs: float = 0
        self.d = range(0)
        self.j = range(0)
        self.ems_power = _IndexedVarView({})
        self.device_power_up = _IndexedVarView({})
        self.device_power_down = _IndexedVarView({})
        self.device_power_sign = _IndexedVarView({})


def _column(df: pd.DataFrame, name: str) -> np.ndarray:
    """Return a DataFrame column as a float array (NaN featuring as np.nan)."""
    return df[name].astype(float).to_numpy()


def _column_or_default(df: pd.DataFrame, name: str, default: float) -> np.ndarray:
    """Return a DataFrame column as a float array, with missing column or NaN values replaced by a default.

    Mirrors e.g. ``device_efficiency`` in the Pyomo implementation ("assume
    perfect efficiency if no efficiency information is available").
    """
    if name not in df.columns:
        return np.full(len(df), float(default))
    values = df[name].astype(float).to_numpy()
    return np.where(np.isnan(values), float(default), values)


def _loss_coefficient_arrays(efficiency: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Vectorized version of ``_loss_coefficients`` in the Pyomo implementation.

    stock[j] = a[j] * stock[j-1] + b[j] * change[j]
    """
    if np.any((efficiency != 1) & (efficiency <= 0)):
        # Mirror math.log raising on non-positive efficiencies
        raise ValueError("math domain error")
    a = efficiency.astype(float)
    b = np.ones_like(a)
    mask = a != 1
    b[mask] = (a[mask] - 1) / np.log(a[mask])
    return a, b


class _RowBuilder:
    """Accumulates constraint rows (in CSR form) for a single HiGHS addRows call.

    Rows that no finite assignment can satisfy (upper bound -inf or lower bound
    +inf) are skipped, mirroring how HiGHS rejects such rows when the appsi
    interface adds them one by one (see module docstring). Free rows
    (-inf, +inf) are also skipped, as they cannot bind.
    """

    def __init__(self):
        self._lower: list[np.ndarray] = []
        self._upper: list[np.ndarray] = []
        self._counts: list[np.ndarray] = []
        self._index: list[np.ndarray] = []
        self._value: list[np.ndarray] = []

    def add_uniform_rows(
        self,
        lower: np.ndarray,
        upper: np.ndarray,
        index: np.ndarray,
        value: np.ndarray,
    ) -> None:
        """Add ``len(lower)`` rows that all have the same number of nonzeros.

        ``index`` and ``value`` must be 2D arrays of shape (n_rows, nnz_per_row).
        """
        lower = np.asarray(lower, dtype=float)
        upper = np.asarray(upper, dtype=float)
        keep = (upper > -infinity) & (lower < infinity)
        keep &= (lower > -infinity) | (upper < infinity)
        if not np.any(keep):
            return
        index = np.asarray(index)[keep]
        value = np.asarray(value, dtype=float)[keep]
        n, nnz = index.shape
        self._lower.append(lower[keep])
        self._upper.append(upper[keep])
        self._counts.append(np.full(n, nnz, dtype=np.int64))
        self._index.append(index.ravel())
        self._value.append(value.ravel())

    def add_row(self, lower: float, upper: float, index: list, value: list) -> None:
        self.add_uniform_rows(
            np.array([lower]),
            np.array([upper]),
            np.array([index], dtype=np.int64),
            np.array([value], dtype=float),
        )

    def build(self):
        if not self._lower:
            return 0, None, None, 0, None, None, None
        lower = np.concatenate(self._lower)
        upper = np.concatenate(self._upper)
        counts = np.concatenate(self._counts)
        index = np.concatenate(self._index).astype(np.int32)
        value = np.concatenate(self._value)
        starts = np.concatenate(([0], np.cumsum(counts)[:-1])).astype(np.int32)
        return len(counts), lower, upper, len(index), starts, index, value


def device_scheduler_highspy(  # noqa C901
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
) -> tuple[list[pd.Series], float, HighspySolverResults, HighspyModel]:
    """Direct HiGHS implementation of ``device_scheduler``.

    Same inputs and same return contract as
    :func:`flexmeasures.data.models.planning.linear_optimization.device_scheduler`,
    which also documents the semantics of all arguments; the third and fourth
    returned objects are lightweight shims rather than Pyomo objects (see
    :class:`HighspySolverResults` and :class:`HighspyModel`).
    """
    import highspy

    model = HighspyModel()

    # If the EMS has no devices, don't bother
    # (mirrors the Pyomo path returning an empty SolverResults, whose
    # termination condition is "unknown" and status "ok")
    if len(device_constraints) == 0:
        return [], 0, HighspySolverResults("unknown", "ok"), model

    # Get timing from first device
    start = device_constraints[0].index.to_pydatetime()[0]
    # Workaround for https://github.com/pandas-dev/pandas/issues/53643. Was: resolution = pd.to_timedelta(device_constraints[0].index.freq)
    resolution = pd.to_timedelta(device_constraints[0].index.freq).to_pytimedelta()
    end = device_constraints[0].index.to_pydatetime()[-1] + resolution

    # Normalise EMS constraints to a list of (DataFrame, device-group) pairs.
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

    # Group keys are namespaced strings, as in the Pyomo implementation.
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

    # Devices sharing a stock may not declare different storage efficiencies
    # or initial stocks (the stock recursion is modelled once per stock group).
    for g, group_devices in group_to_devices.items():
        if len(group_devices) > 1:
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
        from flexmeasures.data.models.planning.utils import initialize_df

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

    # commodity -> set(device indices)
    commodity_devices: dict = {}
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

    # This transformation is solver-agnostic and shared with the Pyomo backend.
    from flexmeasures.data.models.planning.linear_optimization import (
        convert_commitments_to_subcommitments,
    )

    commitments, commitment_mapping = convert_commitments_to_subcommitments(commitments)

    device_group_lookup: dict[int, dict] = {}
    for c, df in enumerate(commitments):
        # Stock-scoped commitments couple to their stock group as a whole.
        if "stock" in df.columns and pd.notna(df["stock"].iloc[0]):
            stock_group_key = f"stock:{int(df['stock'].iloc[0])}"
            if stock_group_key in group_to_devices:
                device_group_lookup[c] = {
                    stock_group_key: {group_to_devices[stock_group_key][0]}
                }
                continue

        if "device" not in df.columns:
            # EMS-level commitment: no device grouping needed here.
            continue

        has_device_group = "device_group" in df.columns
        if has_device_group:
            rows = df[["device", "device_group"]].dropna()
        else:
            # Backwards-compatible default: each device is its own group.
            rows = df[["device"]].dropna()

        device_group_lookup[c] = {}

        for _, row in rows.iterrows():
            d = row["device"]
            g = row["device_group"] if has_device_group else d

            if isinstance(d, (list, tuple, set, np.ndarray)):
                devices = set(d)
            else:
                devices = {d}

            device_group_lookup[c].setdefault(g, set()).update(devices)

    # Oversimplified check for a convex cost curve (mirrors the Pyomo path)
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
        convex_cost_curve = True

    bigM_columns = ["derivative max", "derivative min", "derivative equals"]
    # Compute a good value for our Big-Ms
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

    # ---------------------------------------------------------------
    # Numeric model data (vectorized versions of the Pyomo Param rules)
    # ---------------------------------------------------------------
    D = len(device_constraints)
    T = len(device_constraints[0].index)
    C = len(commitments)

    stock_min = np.empty((D, T))  # device_min_select
    stock_max = np.empty((D, T))  # device_max_select
    deriv_min = np.empty((D, T))  # device_derivative_min_select
    deriv_max = np.empty((D, T))  # device_derivative_max_select
    eff = np.empty((D, T))  # device_efficiency
    down_eff = np.empty((D, T))  # device_derivative_down_efficiency
    up_eff = np.empty((D, T))  # device_derivative_up_efficiency
    delta = np.empty((D, T))  # stock delta

    with np.errstate(invalid="ignore"):
        for d in range(D):
            dc = device_constraints[d]
            minv = _column(dc, "min")
            maxv = _column(dc, "max")
            eqv = _column(dc, "equals")
            # make min <= equals <= max where equals is given (see Pyomo reference)
            eq_hi = np.where(np.isnan(eqv), np.nan, np.fmax(eqv, minv))
            eq_lo = np.where(np.isnan(eqv), np.nan, np.fmin(eqv, maxv))
            stock_max[d] = np.where(
                np.isnan(maxv) & np.isnan(eqv), infinity, np.fmin(maxv, eq_hi)
            )
            stock_min[d] = np.where(
                np.isnan(minv) & np.isnan(eqv), -infinity, np.fmax(minv, eq_lo)
            )

            dminv = _column(dc, "derivative min")
            dmaxv = _column(dc, "derivative max")
            deqv = _column(dc, "derivative equals")
            deriv_max[d] = np.where(
                np.isnan(dmaxv) & np.isnan(deqv), infinity, np.fmin(dmaxv, deqv)
            )
            deriv_min[d] = np.where(
                np.isnan(dminv) & np.isnan(deqv), -infinity, np.fmax(dminv, deqv)
            )

            eff[d] = _column_or_default(dc, "efficiency", 1)
            down_eff[d] = _column_or_default(dc, "derivative down efficiency", 1)
            up_eff[d] = _column_or_default(dc, "derivative up efficiency", 1)
            delta[d] = _column(dc, "stock delta")

    def _initial_stock_of(d) -> float:
        if isinstance(initial_stock, list):
            # No initial stock defined for inflexible device
            return initial_stock[int(d)] if d < len(initial_stock) else 0
        return initial_stock

    # ---------------------------------------------------------------
    # Column (variable) layout
    # ---------------------------------------------------------------
    stock_group_keys = sorted(group_to_devices)
    G = len(stock_group_keys)
    group_index = {g: i for i, g in enumerate(stock_group_keys)}

    nd = D * T
    col_ems = 0  # ems_power[d, j] at col_ems + d * T + j
    col_down = nd  # device_power_down[d, j]
    col_up = 2 * nd  # device_power_up[d, j]
    col_sign = 3 * nd  # device_power_sign[d, j] (binary)
    col_stock = 4 * nd  # group_stock[g, j] at col_stock + g * T + j
    col_cdown = col_stock + G * T  # commitment_downwards_deviation[c]
    col_cup = col_cdown + C  # commitment_upwards_deviation[c]
    ncol = col_cup + C
    col_csign = None  # commitment_sign[c] (binary; only if non-convex)
    if not convex_cost_curve:
        col_csign = ncol
        ncol += C
    band_pairs = [
        (d, b) for d in sorted(band_lookup) for b in range(len(band_lookup[d]))
    ]
    band_col = {}  # (d, b) -> first column of its T binary variables
    col_band = ncol
    for i, (d, b) in enumerate(band_pairs):
        band_col[(d, b)] = col_band + i * T
    ncol += len(band_pairs) * T

    lower = np.full(ncol, -infinity)
    upper = np.full(ncol, infinity)
    cost = np.zeros(ncol)

    # device_power_down: [min(derivative min, 0), 0] (bounds replace the
    # NonPositiveReals domain + device_down_derivative_bounds constraints)
    lower[col_down : col_down + nd] = np.minimum(deriv_min, 0).ravel()
    upper[col_down : col_down + nd] = 0
    # device_power_up: [0, max(0, derivative max)]
    lower[col_up : col_up + nd] = 0
    upper[col_up : col_up + nd] = np.maximum(deriv_max, 0).ravel()
    # device_power_sign: binary
    lower[col_sign : col_sign + nd] = 0
    upper[col_sign : col_sign + nd] = 1
    # commitment deviations: down <= 0 <= up
    upper[col_cdown : col_cdown + C] = 0
    lower[col_cup : col_cup + C] = 0
    if col_csign is not None:
        lower[col_csign : col_csign + C] = 0
        upper[col_csign : col_csign + C] = 1
    if band_pairs:
        lower[col_band:ncol] = 0
        upper[col_band:ncol] = 1

    # Per-subcommitment data: prices (objective), quantities and bounds
    def _price_of(df: pd.DataFrame, column: str) -> float:
        """Mirrors price_down_select / price_up_select."""
        if column not in df.columns:
            return 0
        price = df[column].iloc[0]
        if pd.isna(price):
            return 0
        return float(price)

    down_price = np.zeros(C)
    up_price = np.zeros(C)
    for c, df in enumerate(commitments):
        down_price[c] = _price_of(df, "downwards deviation price")
        up_price[c] = _price_of(df, "upwards deviation price")
    cost[col_cdown : col_cdown + C] = down_price
    cost[col_cup : col_cup + C] = up_price

    # ---------------------------------------------------------------
    # Rows (constraints)
    # ---------------------------------------------------------------
    rows = _RowBuilder()
    k = np.arange(nd)

    # group_stock_balance: group_stock[g, j] = a[j] * previous + b[j] * change[j]
    # As a row: stock[g,j] - a_j * stock[g,j-1]
    #           - b_j * sum_dev(down/down_eff + up*up_eff) = b_j * sum_dev(delta)
    # (with the a_0 * initial_stock term moved to the RHS for j=0)
    for g_key in stock_group_keys:
        gi = group_index[g_key]
        devs = group_to_devices[g_key]
        d0 = devs[0]
        a, b = _loss_coefficient_arrays(eff[d0])
        delta_sum = delta[devs].sum(axis=0)
        init = _initial_stock_of(d0)

        # j = 0
        idx0 = [col_stock + gi * T]
        val0 = [1.0]
        for dev in devs:
            idx0 += [col_down + dev * T, col_up + dev * T]
            val0 += [-b[0] / down_eff[dev, 0], -b[0] * up_eff[dev, 0]]
        rhs0 = b[0] * delta_sum[0] + a[0] * init
        rows.add_row(rhs0, rhs0, idx0, val0)

        # j >= 1
        if T > 1:
            js = np.arange(1, T)
            idx_cols = [col_stock + gi * T + js, col_stock + gi * T + js - 1]
            val_cols = [np.ones(T - 1), -a[js]]
            for dev in devs:
                idx_cols += [col_down + dev * T + js, col_up + dev * T + js]
                val_cols += [-b[js] / down_eff[dev, js], -b[js] * up_eff[dev, js]]
            rhs = b[js] * delta_sum[js]
            rows.add_uniform_rows(
                rhs, rhs, np.column_stack(idx_cols), np.column_stack(val_cols)
            )

    # device_bounds (constraints on the device's stock):
    # device_min <= group_stock[group(d), j] - initial_stock(d) <= device_max
    for d in range(D):
        gi = group_index[device_to_group[d]]
        init = _initial_stock_of(d)
        js = np.arange(T)
        rows.add_uniform_rows(
            stock_min[d] + init,
            stock_max[d] + init,
            (col_stock + gi * T + js)[:, None],
            np.ones((T, 1)),
        )

    # device_derivative_bounds: derivative min <= down + up <= derivative max
    rows.add_uniform_rows(
        deriv_min.ravel(),
        deriv_max.ravel(),
        np.column_stack([col_down + k, col_up + k]),
        np.tile([1.0, 1.0], (nd, 1)),
    )

    # device_up_derivative_sign: up <= Md * sign
    rows.add_uniform_rows(
        np.full(nd, -infinity),
        np.zeros(nd),
        np.column_stack([col_up + k, col_sign + k]),
        np.tile([1.0, -Md], (nd, 1)),
    )
    # device_down_derivative_sign: -down <= Md * (1 - sign)
    rows.add_uniform_rows(
        np.full(nd, -infinity),
        np.full(nd, float(Md)),
        np.column_stack([col_down + k, col_sign + k]),
        np.tile([-1.0, Md], (nd, 1)),
    )

    # device_derivative_equalities: up + down - ems_power = 0
    rows.add_uniform_rows(
        np.zeros(nd),
        np.zeros(nd),
        np.column_stack([col_up + k, col_down + k, col_ems + k]),
        np.tile([1.0, 1.0, -1.0], (nd, 1)),
    )

    # ems_derivative_bounds: ems min <= sum of device flows <= ems max
    for g, ems_df in enumerate(ems_constraints_list):
        devices = ems_constraint_device_groups[g]
        if not devices:
            continue
        v_max = _column(ems_df, "derivative max")
        v_min = _column(ems_df, "derivative min")
        ems_max = np.where(np.isnan(v_max), infinity, v_max)
        ems_min = np.where(np.isnan(v_min), -infinity, v_min)
        js = np.arange(T)
        idx = np.column_stack([col_ems + int(d) * T + js for d in devices])
        rows.add_uniform_rows(ems_min, ems_max, idx, np.ones_like(idx, dtype=float))

    # commitment_up/down_derivative_sign (only for non-convex cost curves):
    # up deviation active only if sign points up, down deviation only if down
    if col_csign is not None and C > 0:
        cs = np.arange(C)
        rows.add_uniform_rows(
            np.full(C, -infinity),
            np.zeros(C),
            np.column_stack([col_cup + cs, col_csign + cs]),
            np.tile([1.0, -Mc], (C, 1)),
        )
        rows.add_uniform_rows(
            np.full(C, -infinity),
            np.full(C, float(Mc)),
            np.column_stack([col_cdown + cs, col_csign + cs]),
            np.tile([-1.0, Mc], (C, 1)),
        )

    # grouped_commitment_equalities: couple each commitment's baseline (plus
    # deviation variables) to the summed flow (FlowCommitment) or stock
    # (StockCommitment) of each of its device groups:
    #   lb <= quantity + down_dev + up_dev - sum_over_group <= ub
    # where lb is 0 iff the commitment prices upwards deviations and ub is 0
    # iff it prices downwards deviations (one-sided otherwise).
    # NB the ems_flow_commitment_equalities of the Pyomo implementation are
    # deliberately not built here; they are free rows (see module docstring).
    for c, df in enumerate(commitments):
        groups = device_group_lookup.get(c, {})
        if not groups:
            continue
        quantity = _column(df, "quantity")
        jj = df["j"].to_numpy(dtype=np.int64)
        # A NaN quantity deactivates the commitment at that time step
        # (NaN was mapped to -inf in the Pyomo implementation's Param).
        active = ~(np.isnan(quantity) | (quantity == -infinity))
        if not np.any(active):
            continue
        quantity = quantity[active]
        jj = jj[active]
        lb = 0.0 if "upwards deviation price" in df.columns else -infinity
        ub = 0.0 if "downwards deviation price" in df.columns else infinity
        is_stock = df["class"].apply(lambda cl: cl == StockCommitment).all()
        n_rows = len(jj)
        for g, devices_in_group in groups.items():
            if not devices_in_group:
                continue
            idx_cols = [
                np.full(n_rows, col_cdown + c),
                np.full(n_rows, col_cup + c),
            ]
            val_cols = [np.ones(n_rows), np.ones(n_rows)]
            if is_stock:
                # Aggregate coefficients per stock group column and move the
                # initial stocks into the row bounds.
                stock_coefficients: dict[int, float] = {}
                initial_stock_sum = 0.0
                for dev in devices_in_group:
                    base = col_stock + group_index[device_to_group[int(dev)]] * T
                    stock_coefficients[base] = stock_coefficients.get(base, 0.0) - 1.0
                    initial_stock_sum += _initial_stock_of(dev)
                for base, coefficient in stock_coefficients.items():
                    idx_cols.append(base + jj)
                    val_cols.append(np.full(n_rows, coefficient))
                offset = initial_stock_sum
            else:
                for dev in devices_in_group:
                    idx_cols.append(col_ems + int(dev) * T + jj)
                    val_cols.append(np.full(n_rows, -1.0))
                offset = 0.0
            rows.add_uniform_rows(
                lb - quantity - offset,
                ub - quantity - offset,
                np.column_stack(idx_cols),
                np.column_stack(val_cols),
            )

    # Power bands (S2 operation modes): each banded device runs in exactly one
    # band per time step, and its power must lie within the chosen band.
    for d in sorted(band_lookup):
        bands = band_lookup[d]
        js = np.arange(T)
        band_cols = [band_col[(d, b)] + js for b in range(len(bands))]
        # device_band_choice: sum_b band[d, b, j] == 1
        rows.add_uniform_rows(
            np.ones(T),
            np.ones(T),
            np.column_stack(band_cols),
            np.ones((T, len(bands))),
        )
        # device_band_power_lower: down + up - sum_b band * band_min >= 0
        rows.add_uniform_rows(
            np.zeros(T),
            np.full(T, infinity),
            np.column_stack([col_down + d * T + js, col_up + d * T + js] + band_cols),
            np.tile(
                [1.0, 1.0] + [-float(bands[b][0]) for b in range(len(bands))], (T, 1)
            ),
        )
        # device_band_power_upper: down + up - sum_b band * band_max <= 0
        rows.add_uniform_rows(
            np.full(T, -infinity),
            np.zeros(T),
            np.column_stack([col_down + d * T + js, col_up + d * T + js] + band_cols),
            np.tile(
                [1.0, 1.0] + [-float(bands[b][1]) for b in range(len(bands))], (T, 1)
            ),
        )

    # ---------------------------------------------------------------
    # Build and solve the HiGHS model
    # ---------------------------------------------------------------
    h = highspy.Highs()

    h.addVars(ncol, lower, upper)
    h.changeColsCost(ncol, np.arange(ncol, dtype=np.int32), cost)

    # Binary variables: device signs, commitment signs (if any) and bands
    integer_cols = [np.arange(col_sign, col_sign + nd, dtype=np.int32)]
    if col_csign is not None:
        integer_cols.append(np.arange(col_csign, col_csign + C, dtype=np.int32))
    if band_pairs:
        integer_cols.append(np.arange(col_band, ncol, dtype=np.int32))
    integer_cols = np.concatenate(integer_cols)
    if len(integer_cols) > 0:
        h.changeColsIntegrality(
            len(integer_cols),
            integer_cols,
            np.full(
                len(integer_cols), int(highspy.HighsVarType.kInteger), dtype=np.uint8
            ),
        )

    nrow, row_lower, row_upper, nnz, row_starts, a_index, a_value = rows.build()
    if nrow > 0:
        h.addRows(nrow, row_lower, row_upper, nnz, row_starts, a_index, a_value)

    # Apply the same solver options as the Pyomo path applies for HiGHS solvers
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
    if configured_options:
        from flexmeasures.data.models.planning.linear_optimization import (
            validate_highs_options,
        )

        validate_highs_options(configured_options)
    profile.update(configured_options)

    for option_name, option_value in profile.items():
        h.setOptionValue(option_name, option_value)

    h.run()

    status = h.getModelStatus()
    termination_condition = {
        highspy.HighsModelStatus.kOptimal: "optimal",
        highspy.HighsModelStatus.kInfeasible: "infeasible",
        highspy.HighsModelStatus.kUnboundedOrInfeasible: "infeasibleOrUnbounded",
        highspy.HighsModelStatus.kUnbounded: "unbounded",
        highspy.HighsModelStatus.kTimeLimit: "maxTimeLimit",
        highspy.HighsModelStatus.kIterationLimit: "maxIterations",
    }.get(status, str(status))
    results = HighspySolverResults(
        termination_condition,
        "ok" if status == highspy.HighsModelStatus.kOptimal else "warning",
    )

    solution = h.getSolution()
    if solution.value_valid:
        col_value = np.asarray(solution.col_value)
    else:
        # Mirror the Pyomo path: when no feasible solution was found, the
        # variables keep their initial values (all zeros).
        col_value = np.zeros(ncol)

    # ---------------------------------------------------------------
    # Extract results (mirroring the Pyomo path's return contract)
    # ---------------------------------------------------------------
    ems_values = col_value[col_ems : col_ems + nd].reshape(D, T)
    down_values = col_value[col_down : col_down + nd].reshape(D, T)
    up_values = col_value[col_up : col_up + nd].reshape(D, T)
    sign_values = col_value[col_sign : col_sign + nd].reshape(D, T)
    cdown_values = col_value[col_cdown : col_cdown + C]
    cup_values = col_value[col_cup : col_cup + C]

    # Sum the planned costs in the same (subcommitment) order as the Pyomo path
    subcommitment_costs = {
        c: float(cdown_values[c]) * down_price[c] + float(cup_values[c]) * up_price[c]
        for c in range(C)
    }
    planned_costs = 0
    for c in range(C):
        planned_costs += subcommitment_costs[c]

    # Map subcommitment costs to commitments
    commitment_costs: dict = {}
    for g, v in subcommitment_costs.items():
        c = commitment_mapping[g]
        commitment_costs[c] = commitment_costs.get(c, 0) + v

    planned_power_per_device = []
    for d in range(D):
        planned_power_per_device.append(
            initialize_series(
                data=list(ems_values[d]),
                start=start,
                end=end,
                resolution=to_offset(resolution),
            )
        )

    commodity_costs: dict = {}
    for c in range(C):
        commodity = None
        if "commodity" in commitments[c].columns:
            commodity = commitments[c]["commodity"].iloc[0]
        if commodity is None or (isinstance(commodity, float) and np.isnan(commodity)):
            continue
        commodity_costs[commodity] = (
            commodity_costs.get(commodity, 0) + subcommitment_costs[c]
        )

    model.commitment_costs = commitment_costs
    model.commodity_costs = commodity_costs
    model.costs = planned_costs
    model.d = range(D)
    model.j = range(T)
    model.ems_power = _IndexedVarView(
        {(d, j): float(ems_values[d, j]) for d in range(D) for j in range(T)}
    )
    model.device_power_up = _IndexedVarView(
        {(d, j): float(up_values[d, j]) for d in range(D) for j in range(T)}
    )
    model.device_power_down = _IndexedVarView(
        {(d, j): float(down_values[d, j]) for d in range(D) for j in range(T)}
    )
    model.device_power_sign = _IndexedVarView(
        {(d, j): float(sign_values[d, j]) for d in range(D) for j in range(T)}
    )

    return planned_power_per_device, planned_costs, results, model
