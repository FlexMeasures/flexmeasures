"""Direct HiGHS (highspy) implementation of the device scheduler.

.. warning:: TWO MODELS TO KEEP IN SYNC

    This module deliberately duplicates the mathematical model of the Pyomo implementation,
    :func:`flexmeasures.data.models.planning.linear_optimization.device_scheduler`,
    building the LP/MILP directly with the HiGHS Python API (``highspy``) instead.
    The Pyomo implementation is the semantic reference:
    any change to the variables, constraints or objective in ``device_scheduler`` MUST be mirrored here (and vice versa),
    and the equivalence tests in ``tests/test_highspy_equivalence.py`` should be extended accordingly.
    This trade-off (a second model to maintain) was accepted
    because bypassing the Pyomo layer cuts roughly a second (single device) to several seconds (multiple devices)
    of model construction and solution-ingestion overhead per scheduling job,
    while the direct build takes milliseconds.

Deviations from the Pyomo implementation (all verified against the behavior of the ``appsi_highs`` path):

- Rows whose computed bounds are impossible to satisfy for any finite value
  (upper bound of -inf, or lower bound of +inf, as happens when a commitment quantity is +/-inf) are skipped.
  On the Pyomo path such rows are rejected by HiGHS' ``addRow`` (called by appsi) and thereby silently dropped,
  with the same net effect.
- Solver results and model objects are lightweight shims
  (see :class:`HighspySolverResults` and :class:`HighspyModel`)
  that expose the attributes callers actually consume, rather than Pyomo objects.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from flexmeasures.data.models.planning import (
    Commitment,
    FlowCommitment,
    StockCommitment,
)
from flexmeasures.data.models.planning.scheduling_problem import (
    aggregate_commodity_costs,
    aggregate_subcommitment_costs,
    planned_power_per_device,
    prepare_scheduling_problem,
    solver_options,
)

infinity = float("inf")


class _SolverInformation:
    """Mimics the ``solver`` entry of a Pyomo ``SolverResults`` object.

    Named after Pyomo's own ``pyomo.opt.results.solver.SolverInformation``, which is what that entry holds.
    """

    def __init__(self, termination_condition: str, status: str):
        #: str containing "optimal", "infeasible", etc.
        #: Mirrors Pyomo's str-valued TerminationCondition enum,
        #: which supports both ``== "optimal"`` and ``"infeasible" in ...`` checks.
        self.termination_condition = termination_condition
        self.status = status


class HighspySolverResults:
    """Small stand-in for Pyomo's ``SolverResults``.

    Callers only consume ``results.solver.termination_condition`` (a string containing "optimal"/"infeasible")
    and ``results.solver.status``.
    """

    def __init__(self, termination_condition: str, status: str):
        self.solver = _SolverInformation(termination_condition, status)


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
    - ``costs``: the objective value
      (a float; ``pyomo.environ.value()`` passes floats through unchanged, so ``value(model.costs)`` keeps working)
    - ``d`` and ``j``: the device and datetime index ranges
    - ``ems_power``, ``device_power_up``, ``device_power_down``, ``device_power_sign``:
      indexed variable views supporting ``var[d, j].value`` and ``var.extract_values()``
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

    Mirrors e.g. ``device_efficiency`` in the Pyomo implementation
    ("assume perfect efficiency if no efficiency information is available").
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

    Rows that no finite assignment can satisfy (upper bound -inf or lower bound +inf) are skipped,
    mirroring how HiGHS rejects such rows when the appsi interface adds them one by one (see module docstring).
    Free rows (-inf, +inf) are also skipped, as they cannot bind.
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
    )

    # Local aliases, so that the model below reads as it did before the (solver-agnostic)
    # input handling moved to the scheduling_problem module.
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

    # grouped_commitment_equalities:
    # couple each commitment's baseline (plus deviation variables)
    # to the summed flow (FlowCommitment) or stock (StockCommitment) of each of its device groups:
    #   lb <= quantity + down_dev + up_dev - sum_over_group <= ub
    # where lb is 0 iff the commitment prices upwards deviations,
    # and ub is 0 iff it prices downwards deviations (one-sided otherwise).
    def _active_rows(df: pd.DataFrame):
        """The commitment's active time steps and its row bounds.

        A NaN quantity deactivates the commitment at that time step.
        The Pyomo implementation maps such a quantity to -inf in its Param
        and lets the resulting row (whose lower bound works out to +inf) be rejected by HiGHS;
        dropping it here has the same effect.
        """
        quantity = _column(df, "quantity")
        jj = df["j"].to_numpy(dtype=np.int64)
        active = ~(np.isnan(quantity) | (quantity == -infinity))
        lb = 0.0 if "upwards deviation price" in df.columns else -infinity
        ub = 0.0 if "downwards deviation price" in df.columns else infinity
        return quantity[active], jj[active], lb, ub

    def _add_commitment_rows(c, quantity, jj, lb, ub, devices, is_stock) -> None:
        """Bind commitment ``c`` to the summed flow or stock of ``devices``."""
        n_rows = len(jj)
        idx_cols = [
            np.full(n_rows, col_cdown + c),
            np.full(n_rows, col_cup + c),
        ]
        val_cols = [np.ones(n_rows), np.ones(n_rows)]
        if is_stock:
            # Aggregate coefficients per stock group column,
            # and move the initial stocks into the row bounds.
            stock_coefficients: dict[int, float] = {}
            initial_stock_sum = 0.0
            for dev in devices:
                base = col_stock + group_index[device_to_group[int(dev)]] * T
                stock_coefficients[base] = stock_coefficients.get(base, 0.0) - 1.0
                initial_stock_sum += _initial_stock_of(dev)
            for base, coefficient in stock_coefficients.items():
                idx_cols.append(base + jj)
                val_cols.append(np.full(n_rows, coefficient))
            offset = initial_stock_sum
        else:
            for dev in devices:
                idx_cols.append(col_ems + int(dev) * T + jj)
                val_cols.append(np.full(n_rows, -1.0))
            offset = 0.0
        rows.add_uniform_rows(
            lb - quantity - offset,
            ub - quantity - offset,
            np.column_stack(idx_cols),
            np.column_stack(val_cols),
        )

    for c, df in enumerate(commitments):
        groups = device_group_lookup.get(c, {})
        if not groups:
            continue
        quantity, jj, lb, ub = _active_rows(df)
        if len(jj) == 0:
            continue
        is_stock = df["class"].apply(lambda cl: cl == StockCommitment).all()
        for g, devices_in_group in groups.items():
            if not devices_in_group:
                continue
            _add_commitment_rows(c, quantity, jj, lb, ub, devices_in_group, is_stock)

    # ems_flow_commitment_equalities: an EMS-level flow commitment binds the summed flow of every device,
    # or of its commodity's devices when it names a commodity.
    # A commitment that names devices is skipped here, being already bound per device group above;
    # binding it twice would over-constrain it.
    for c, df in enumerate(commitments):
        if device_group_lookup.get(c):
            continue
        if df["class"].iloc[0] != FlowCommitment:
            continue
        if "commodity" not in df.columns:
            # Legacy behavior: no commodity, so sum over all devices.
            devices: object = range(D)
        else:
            commodity = df["commodity"].iloc[0]
            if pd.isna(commodity):
                devices = range(D)
            else:
                devices = problem.commodity_devices.get(commodity, set())
                if not devices:
                    continue
        quantity, jj, lb, ub = _active_rows(df)
        if len(jj) == 0:
            continue
        _add_commitment_rows(c, quantity, jj, lb, ub, devices, is_stock=False)

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

    # The same options the Pyomo path applies for HiGHS solvers ("highspy" matches on "highs"),
    # so the two backends cannot disagree on tolerances.
    for option_name, option_value in solver_options("highspy").items():
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

    planned_power = planned_power_per_device(ems_values, start, end, resolution)

    model.commitment_costs = aggregate_subcommitment_costs(
        subcommitment_costs, commitment_mapping
    )
    model.commodity_costs = aggregate_commodity_costs(commitments, subcommitment_costs)
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

    return planned_power, planned_costs, results, model
