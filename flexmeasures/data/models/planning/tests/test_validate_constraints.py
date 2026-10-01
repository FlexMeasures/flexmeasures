"""Tests for the validation of device constraints.

The vectorised validation must report exactly what the original pd.eval-based validation reported,
which is kept below as a reference implementation.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest
import pytz

from flexmeasures.data.models.planning.storage import (
    StorageScheduler,
    prepend_series,
    validate_constraint,
    validate_constraints,
    validate_power_constraints,
    validate_storage_constraints,
)
from flexmeasures.data.models.planning.utils import initialize_df

TZ = pytz.timezone("Europe/Amsterdam")
START = TZ.localize(datetime(2015, 1, 1))


def reference_validate_power_constraints(constraints: pd.DataFrame) -> list[dict]:
    """The pd.eval-based validate_power_constraints as it was before vectorisation."""
    _constraints = constraints.copy()
    _constraints = _constraints.rename(
        columns={c: c.replace(" ", "_") + "(t)" for c in _constraints.columns}
    )
    violations = []
    violations += validate_constraint(
        _constraints, "derivative_min(t)", "<=", "derivative_max(t)"
    )
    violations += validate_constraint(
        _constraints, "derivative_min(t)", "<=", "derivative_equals(t)"
    )
    violations += validate_constraint(
        _constraints, "derivative_equals(t)", "<=", "derivative_max(t)"
    )
    return violations


def reference_validate_storage_constraints(
    constraints, soc_at_start, soc_min, soc_max, resolution
) -> list[dict]:
    """The pd.eval-based validate_storage_constraints as it was before vectorisation."""
    _constraints = constraints.copy()
    _constraints = _constraints.rename(
        columns={c: c.replace(" ", "_") + "(t)" for c in _constraints.columns}
    )
    violations = []

    if soc_min is not None:
        soc_min = (soc_min - soc_at_start) * timedelta(hours=1) / resolution
        _constraints["soc_min(t)"] = soc_min
        violations += validate_constraint(_constraints, "soc_min(t)", "<=", "min(t)")
    else:
        soc_min = np.nan

    if soc_max is not None:
        soc_max = (soc_max - soc_at_start) * timedelta(hours=1) / resolution
        _constraints["soc_max(t)"] = soc_max
        violations += validate_constraint(_constraints, "max(t)", "<=", "soc_max(t)")
    else:
        soc_max = np.nan

    violations += validate_constraint(_constraints, "min(t)", "<=", "max(t)")
    violations += validate_constraint(_constraints, "min(t)", "<=", "equals(t)")
    violations += validate_constraint(_constraints, "equals(t)", "<=", "max(t)")

    _constraints["factor_w_wh(t)"] = resolution / timedelta(hours=1)
    _constraints["min(t-1)"] = prepend_series(_constraints["min(t)"], soc_min)
    _constraints["equals(t-1)"] = prepend_series(
        _constraints["equals(t)"], soc_at_start
    )
    _constraints["max(t-1)"] = prepend_series(_constraints["max(t)"], soc_max)

    derivative_max = "derivative_max(t) * factor_w_wh(t)"
    derivative_min = "derivative_min(t) * factor_w_wh(t)"
    violations += validate_constraint(
        _constraints, "equals(t) - equals(t-1)", "<=", derivative_max
    )
    violations += validate_constraint(
        _constraints, derivative_min, "<=", "equals(t) - equals(t-1)"
    )
    violations += validate_constraint(
        _constraints, "min(t) - max(t-1)", "<=", derivative_max
    )
    violations += validate_constraint(
        _constraints, derivative_min, "<=", "max(t) - min(t-1)"
    )
    violations += validate_constraint(
        _constraints, "equals(t) - max(t-1)", "<=", derivative_max
    )
    violations += validate_constraint(
        _constraints, derivative_min, "<=", "equals(t) - min(t-1)"
    )
    return violations


def make_constraints(resolution: timedelta, n_steps: int, **columns) -> pd.DataFrame:
    """A frame with the storage scheduler's columns, of which the given ones are set (scalars or lists)."""
    df = initialize_df(
        StorageScheduler.COLUMNS, START, START + n_steps * resolution, resolution
    )
    for name, value in columns.items():
        df[name] = value
    return df


def random_constraints(rng: np.random.Generator) -> tuple[pd.DataFrame, dict]:
    """A random constraints frame and the other arguments of validate_storage_constraints.

    Values come from a small grid, so that equal boundaries are common,
    and some come with float noise, to exercise the rounding.
    Columns are randomly entirely unset, partly unset, or set (as integers or floats).
    """
    resolution = [timedelta(minutes=15), timedelta(hours=1)][rng.integers(2)]
    n_steps = int(rng.integers(3, 13))
    columns = {}
    for name, low, high in [
        ("min", -2, 6),
        ("max", 2, 10),
        ("equals", -2, 10),
        ("derivative min", -4, 3),
        ("derivative max", 0, 5),
        ("derivative equals", -4, 5),
    ]:
        mode = rng.choice(["unset", "partial", "integers", "floats"])
        if mode == "unset":
            continue
        values = rng.integers(low, high, n_steps).astype(float)
        if mode == "floats":
            values += rng.choice([0, 1e-9, 0.5, 0.1 + 0.2 - 0.3], n_steps)
        if mode == "partial":
            values[rng.random(n_steps) < 0.5] = np.nan
        columns[name] = values.astype(int) if mode == "integers" else values
    kwargs = dict(
        soc_at_start=float(rng.integers(0, 5)),
        soc_min=[None, 0.0, 1.0][rng.integers(3)],
        soc_max=[None, 8.0, 12.0][rng.integers(3)],
        resolution=resolution,
    )
    return make_constraints(resolution, n_steps, **columns), kwargs


def test_vectorised_validation_matches_reference():
    """Seeded random frames yield identical violations, in identical order, as the pd.eval-based reference."""
    rng = np.random.default_rng(20150101)
    conditions_seen = set()
    n_violations = 0
    for _ in range(60):
        constraints, kwargs = random_constraints(rng)
        original = constraints.copy()

        storage = validate_storage_constraints(constraints, **kwargs)
        assert storage == reference_validate_storage_constraints(constraints, **kwargs)
        power = validate_power_constraints(constraints)
        assert power == reference_validate_power_constraints(constraints)

        pd.testing.assert_frame_equal(constraints, original)
        conditions_seen |= {v["condition"] for v in storage + power}
        n_violations += len(storage) + len(power)

    # The random frames must exercise every kind of check, otherwise the comparison above proves little.
    assert n_violations > 100
    assert len(conditions_seen) == 14, conditions_seen


@pytest.mark.parametrize(
    "columns, kwargs, condition, violation",
    [
        (
            {"min": 5, "max": 2},
            {},
            "min(t) <= max(t)",
            "min(t) [5] <=max(t) [2] ",
        ),
        (
            {"min": 1},
            {"soc_min": 3.0},
            "soc_min(t) <= min(t)",
            "soc_min(t) [3.0] <=min(t) [1] ",
        ),
        (
            {"max": 9},
            {"soc_max": 8.0},
            "max(t) <= soc_max(t)",
            "max(t) [9] <=soc_max(t) [8.0] ",
        ),
        (
            {"min": 4, "equals": 3},
            {},
            "min(t) <= equals(t)",
            "min(t) [4] <=equals(t) [3] ",
        ),
        (
            {"max": 3, "equals": 4},
            {},
            "equals(t) <= max(t)",
            "equals(t) [4] <=max(t) [3] ",
        ),
    ],
)
def test_same_time_frame_violation_messages(columns, kwargs, condition, violation):
    """A same-time-frame violation is reported at its time step, with the column values filled in."""
    constraints = make_constraints(timedelta(hours=1), 2, **columns)
    kwargs = (
        dict(
            soc_at_start=0.0,
            soc_min=None,
            soc_max=None,
            resolution=timedelta(hours=1),
        )
        | kwargs
    )
    violations = validate_storage_constraints(constraints, **kwargs)
    matching = [v for v in violations if v["condition"] == condition]
    assert len(matching) == 2
    assert [v["dt"] for v in matching] == [
        START.astimezone(pytz.utc),
        (START + timedelta(hours=1)).astimezone(pytz.utc),
    ]
    assert matching[0]["violation"] == violation


def test_time_shifted_violation_message_and_rounding():
    """A ramp faster than the derivative max is reported, but float noise below 6 decimals is not."""
    resolution = timedelta(minutes=15)
    constraints = make_constraints(
        resolution,
        3,
        equals=[0.0, 1.0 + 1e-9, 3.0],
        **{"derivative max": 4.0, "derivative min": -4.0},
    )
    violations = validate_storage_constraints(constraints, 0.0, None, None, resolution)
    assert len(violations) == 1
    assert violations[0]["condition"] == (
        "equals(t) - equals(t-1) <= derivative_max(t) * factor_w_wh(t)"
    )
    assert violations[0]["dt"] == (START + 2 * resolution).astimezone(pytz.utc)
    assert violations[0]["violation"] == (
        "equals(t) [3.0] -equals(t-1) [1.000000001] <=derivative_max(t) [4.0] *factor_w_wh(t) [0.25] "
    )


def test_missing_values_are_not_reported():
    """Time steps where an involved value is missing are skipped, while others are still reported."""
    constraints = make_constraints(
        timedelta(hours=1), 3, min=[5.0, np.nan, 5.0], max=[2.0, 2.0, np.nan]
    )
    violations = validate_storage_constraints(
        constraints, 0.0, None, None, timedelta(hours=1)
    )
    assert [v["dt"] for v in violations if v["condition"] == "min(t) <= max(t)"] == [
        START.astimezone(pytz.utc)
    ]


def test_unsupported_inequality_is_rejected():
    constraints = make_constraints(timedelta(hours=1), 2, min=1, max=2)
    with pytest.raises(ValueError, match="not supported"):
        validate_constraints(constraints, [("min", "<>", "max")])
