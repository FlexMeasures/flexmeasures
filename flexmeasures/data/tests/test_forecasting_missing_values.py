"""Tests for the filling of missing input values in the forecasting pipelines.

``BasePipeline.detect_and_fill_missing_values`` is compared with a reference copy of the earlier Darts-based implementation.
"""

from __future__ import annotations

import logging
from datetime import datetime
from functools import reduce

import numpy as np
import pandas as pd
import pytest
from darts import TimeSeries
from darts.dataprocessing.transformers import MissingValuesFiller

from flexmeasures.data.models.forecasting.exceptions import NotEnoughDataException
from flexmeasures.data.models.forecasting.pipelines.base import (
    BasePipeline,
    _bound_input_series,
)
from flexmeasures.data.models.time_series import Sensor


def _reference_detect_and_fill_missing_values(
    self,
    df: pd.DataFrame,
    sensors: list[Sensor],
    sensor_names: list[str],
    start: datetime,
    end: datetime,
    interpolate_kwargs: dict = None,
    fill: float = 0.0,
) -> TimeSeries:
    """The detect_and_fill_missing_values of main before the pandas fast path, kept as a reference."""
    dfs = []

    for sensor, sensor_name in zip(sensors, sensor_names):

        # check missing data before filling
        if sensor_name in df.columns:
            n_missing = df[sensor_name].isna().sum()
            total = len(df)
            missing_fraction = n_missing / total if total > 0 else 1.0

            if missing_fraction > self.missing_threshold:
                raise NotEnoughDataException(
                    f"Sensor {sensor_name} has {missing_fraction * 100:.1f}% missing values "
                    f"which exceeds the allowed threshold of {self.missing_threshold * 100:.1f}%"
                )

        if df.empty:
            last_event_start = end - pd.Timedelta(
                hours=sensor.event_resolution.total_seconds() / 3600
            )
            new_row_start = pd.DataFrame({"event_start": [start], sensor_name: [None]})
            new_row_end = pd.DataFrame(
                {"event_start": [last_event_start], sensor_name: [None]}
            )
            df = pd.concat([new_row_start, df, new_row_end], ignore_index=True)

            logging.debug(
                f"Sensor {sensor_name} has no data from {start} to {end}. Filling with {fill}."
            )
            transformer = MissingValuesFiller(fill=float(fill))
        else:
            transformer = MissingValuesFiller(fill="auto")

        # Keep only this sensor's own column, so each pass contributes exactly one component.
        # Copying the whole frame would stack every sensor's column once per sensor,
        # handing the model each regressor several times over.
        if sensor_name in df.columns:
            data = df[["event_start", sensor_name]].copy()
        else:
            data = df[["event_start"]].copy()
            data[sensor_name] = np.nan

        # Convert start & end to naive UTC
        start = start.tz_localize(None)
        end = end.tz_localize(None)
        last_event_start = end

        # Ensure the first and last event_starts match the expected dates specified in the CLI arguments
        # Add start time if missing
        if data.empty or (
            data["event_start"].iloc[0] != start and data["event_start"].iloc[0] > start
        ):
            new_row_start = pd.DataFrame({"event_start": [start], sensor_name: [None]})
            data = pd.concat([new_row_start, data], ignore_index=True)

        if data.empty or (
            data["event_start"].iloc[-1] != last_event_start
            and data["event_start"].iloc[-1] < last_event_start
        ):
            new_row_end = pd.DataFrame(
                {"event_start": [last_event_start], sensor_name: [None]}
            )
            data = pd.concat([data, new_row_end], ignore_index=True)

        # Drop duplicate event_starts (keep first)
        if n_extra_points := len(data) - len(data["event_start"].unique()):
            logging.debug(
                f"Data for sensor {sensor_name} contains multiple beliefs about a single event. "
                f"Dropping {n_extra_points} beliefs with duplicate event starts."
            )
            data = data.drop_duplicates("event_start")

        # Convert to Darts TimeSeries & fill
        data_darts = TimeSeries.from_dataframe(
            df=data,
            time_col="event_start",
            fill_missing_dates=True,
            freq=self.target_sensor.event_resolution,
        )
        # Identify gaps in the time index (where timestamp rows are missing)
        data_darts_gaps = data_darts.gaps()

        # Calculate number of missing rows per gap
        data_darts_gaps["missing_rows"] = (
            (data_darts_gaps["gap_end"] - data_darts_gaps["gap_start"])
            / sensor.event_resolution
        ).astype(int)

        # Total missing rows
        total_missing = data_darts_gaps["missing_rows"].sum()

        # Total expected rows in full dataset
        total_expected = int((end - start) / sensor.event_resolution) + 1

        # Fraction of missing rows
        missing_rows_fraction = total_missing / total_expected

        if missing_rows_fraction > self.missing_threshold:
            raise NotEnoughDataException(
                f"Sensor {sensor_name} has {missing_rows_fraction * 100:.1f}% missing values "
                f"which exceeds the allowed threshold of {self.missing_threshold * 100:.1f}%"
            )
        if not data_darts_gaps.empty:
            data_darts = transformer.transform(data_darts, **(interpolate_kwargs or {}))
            logging.debug(
                f"Sensor {sensor_name} has gaps:\n{data_darts_gaps.to_string()}\n"
                "These were filled using `pd.DataFrame.interpolate()`."
            )

        data_darts = _bound_input_series(data_darts, sensor)

        dfs.append(data_darts)

    if len(dfs) == 1:
        data_darts = dfs[0]
    else:
        data_darts = reduce(
            lambda left, right: left.stack(right),
            dfs,
        )
    return data_darts


class _SensorStub:
    """A stand-in for a sensor, with only the attributes the filling step reads."""

    def __init__(self, resolution: pd.Timedelta = pd.Timedelta(hours=1)):
        self.event_resolution = resolution


def _pipeline(threshold: float = 1.0, resolution=pd.Timedelta(hours=1)):
    pipeline = BasePipeline.__new__(BasePipeline)
    pipeline.missing_threshold = threshold
    pipeline.target_sensor = _SensorStub(resolution)
    return pipeline


START = pd.Timestamp("2025-01-01 00:00")
END = START + pd.Timedelta(hours=9)
NAN = np.nan


def _frame(values: dict[str, list[float]], offset: int = 0) -> pd.DataFrame:
    n = len(next(iter(values.values())))
    index = pd.date_range(START + pd.Timedelta(hours=offset), periods=n, freq="h")
    return pd.DataFrame({"event_start": index, **values})


def _fill(
    df,
    names,
    start=START,
    end=END,
    threshold=1.0,
    implementation=BasePipeline.detect_and_fill_missing_values,
    **kwargs,
):
    return implementation(
        _pipeline(threshold),
        df=df,
        sensors=[_SensorStub() for _ in names],
        sensor_names=names,
        start=start,
        end=end,
        **kwargs,
    )


def _values(series: TimeSeries) -> np.ndarray:
    return series.values().ravel()


def test_no_gaps_leaves_values_alone():
    df = _frame({"a": [float(i) for i in range(10)]})
    filled = _fill(df, ["a"])
    np.testing.assert_array_equal(_values(filled), np.arange(10.0))
    assert list(filled.time_index) == list(df["event_start"])
    assert filled.freq == pd.Timedelta(hours=1)
    assert filled.dtype == np.float64


def test_interior_gaps_are_interpolated():
    """Both NaN values and missing rows are interpolated."""
    df = _frame({"a": [0.0, 1.0, NAN, NAN, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0]})
    df = df.drop(index=[6, 7])
    filled = _fill(df, ["a"])
    assert len(filled) == 10
    np.testing.assert_allclose(_values(filled), np.arange(10.0))


def test_missing_start_and_end_rows_are_padded():
    df = _frame({"a": [5.0, 6.0, 7.0]}, offset=2)
    filled = _fill(df, ["a"])
    assert filled.start_time() == START
    assert filled.end_time() == END
    # Both edges take the nearest known value.
    np.testing.assert_allclose(
        _values(filled), [5.0, 5.0, 5.0, 6.0, 7.0, 7.0, 7.0, 7.0, 7.0, 7.0]
    )


def test_duplicate_event_starts_keep_the_first():
    df = _frame({"a": [float(i) for i in range(10)]})
    duplicate = df.iloc[[4]].assign(a=99.0)
    df = pd.concat([df.iloc[:5], duplicate, df.iloc[5:]], ignore_index=True)
    np.testing.assert_allclose(_values(_fill(df, ["a"])), np.arange(10.0))


def test_rows_beyond_the_window_are_kept_whatever_their_order():
    df = _frame({"a": [float(i) for i in range(12)]}).sample(frac=1, random_state=1)
    filled = _fill(df, ["a"])
    assert filled.end_time() == START + pd.Timedelta(hours=11)
    np.testing.assert_allclose(_values(filled), np.arange(12.0))


def test_empty_frame_is_filled_with_the_constant():
    filled = _fill(pd.DataFrame(), ["a"], fill=3.5)
    assert len(filled) == 10
    np.testing.assert_allclose(_values(filled), np.full(10, 3.5))
    assert list(filled.components) == ["a"]


def test_missing_rows_threshold_counts_one_row_fewer_than_a_gap_spans():
    """A gap of 4 missing rows counts as 3 of 10, so a threshold of 0.3 still passes and 0.29 does not."""
    df = _frame({"a": [float(i) for i in range(10)]}).drop(index=[3, 4, 5, 6])
    assert len(_fill(df, ["a"], threshold=0.3)) == 10
    with pytest.raises(NotEnoughDataException, match="30.0% missing values"):
        _fill(df, ["a"], threshold=0.29)


@pytest.mark.parametrize(
    "implementation",
    [
        _reference_detect_and_fill_missing_values,
        BasePipeline.detect_and_fill_missing_values,
    ],
)
@pytest.mark.parametrize("dropped_rows", [[], [7]])
def test_missing_event_start_raises_a_value_error(implementation, dropped_rows):
    """A NaT in the event_start column is an error, with or without other gaps, as it was with Darts."""
    df = _frame({"a": [float(i) for i in range(10)]})
    df.loc[4, "event_start"] = pd.NaT
    with pytest.raises(ValueError):
        _fill(df.drop(index=dropped_rows), ["a"], implementation=implementation)


def test_nan_value_threshold_is_checked_on_the_input_column():
    df = _frame({"a": [0.0, NAN, NAN, NAN, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0]})
    assert len(_fill(df, ["a"], threshold=0.3)) == 10
    with pytest.raises(NotEnoughDataException, match="30.0% missing values"):
        _fill(df, ["a"], threshold=0.29)


def test_several_sensors_are_stacked_in_order():
    df = _frame(
        {
            "b": [float(i) for i in range(10)],
            "a": [10.0 * i for i in range(10)],
        }
    )
    filled = _fill(df, ["b", "a"])
    assert list(filled.components) == ["b", "a"]
    np.testing.assert_allclose(filled.values()[:, 0], np.arange(10.0))
    np.testing.assert_allclose(filled.values()[:, 1], 10.0 * np.arange(10.0))


def test_custom_interpolate_kwargs_still_apply():
    """With a limit of 1 row on both sides, the middle of a 3-row gap stays unfilled."""
    df = _frame({"a": [0.0, 1.0, NAN, NAN, NAN, 5.0, 6.0, 7.0, 8.0, 9.0]})
    filled = _fill(df, ["a"], interpolate_kwargs={"limit": 1})
    np.testing.assert_allclose(
        _values(filled), [0.0, 1.0, 2.0, NAN, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0]
    )


def _random_case(rng: np.random.Generator):
    """Several sensors with NaN runs, dropped rows, trimmed edges and possibly a duplicate event start."""
    n = int(rng.integers(20, 120))
    names = [f"s{i}" for i in range(int(rng.integers(1, 4)))]
    df = _frame({name: rng.normal(size=n) for name in names})
    for name in names:
        for _ in range(int(rng.integers(0, 4))):
            at = int(rng.integers(0, n))
            df.loc[at : at + int(rng.integers(1, 5)), name] = np.nan
    df = df[rng.random(n) >= rng.choice([0.0, 0.05, 0.2])]
    df = df.iloc[int(rng.integers(0, 4)) : len(df) - int(rng.integers(0, 4))]
    if rng.random() < 0.5 and len(df) > 2:
        df = pd.concat([df, df.iloc[[len(df) // 2]].assign(**{names[0]: 99.0})])
        df = df.sort_values("event_start", kind="stable")
    return df.reset_index(drop=True), names, START + pd.Timedelta(hours=n - 1)


def test_matches_the_darts_based_reference():
    """On random cases, and without data, the result (or the refusal) equals that of the Darts-based reference."""
    rng = np.random.default_rng(0)
    cases = [(pd.DataFrame(), ["a"], END, {"fill": fill}) for fill in (0.0, 7.0)]
    for _ in range(50):
        df, names, end = _random_case(rng)
        if len(df):
            cases.append((df, names, end, {"threshold": rng.choice([0.1, 1.0])}))
    for df, names, end, kwargs in cases:
        outcomes = []
        for implementation in (
            BasePipeline.detect_and_fill_missing_values,
            _reference_detect_and_fill_missing_values,
        ):
            try:
                outcomes.append(
                    _fill(
                        df.copy(),
                        names,
                        end=end,
                        implementation=implementation,
                        **kwargs,
                    )
                )
            except NotEnoughDataException as exception:
                outcomes.append(str(exception))
        new, old = outcomes
        if isinstance(old, str):
            assert new == old
            continue
        assert not isinstance(new, str)
        assert new.time_index.equals(old.time_index)
        assert list(new.components) == list(old.components)
        assert new.freq == old.freq
        assert new.dtype == old.dtype
        np.testing.assert_allclose(
            new.values(), old.values(), rtol=1e-12, atol=1e-12, equal_nan=True
        )
