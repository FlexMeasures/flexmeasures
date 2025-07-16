import pytest

import pandas as pd

from flexmeasures.data.models.planning.utils import process_time_series_segments
from flexmeasures.utils.unit_utils import ur


@pytest.mark.parametrize(
    "index, variable_quantity, unit, resolution, resolve_overlaps, expected",
    [
        # Test case 1: Simple case with no overlaps
        (
            pd.date_range("2023-01-01", "2023-01-05", freq="1h", inclusive="left"),
            [
                {
                    "value": 1,
                    "start": pd.Timestamp("2023-01-01"),
                    "end": pd.Timestamp("2023-01-03"),
                },
                {
                    "value": 2,
                    "start": pd.Timestamp("2023-01-03"),
                    "end": pd.Timestamp("2023-01-05"),
                },
            ],
            "dimensionless",
            pd.Timedelta("1h"),
            "first",
            pd.Series(
                [1] * 24 * 2 + [2] * 24 * 2,
                index=pd.date_range(
                    "2023-01-01", "2023-01-05", freq="1h", inclusive="left"
                ),
                name="event_value",
            ),
        ),
        # Test case 2: Resolving overlaps with mean
        (
            pd.date_range("2023-01-01", "2023-01-05", freq="1h", inclusive="left"),
            [
                {
                    "value": 1,
                    "start": pd.Timestamp("2023-01-01"),
                    "end": pd.Timestamp("2023-01-04"),
                },
                {
                    "value": 2,
                    "start": pd.Timestamp("2023-01-03"),
                    "end": pd.Timestamp("2023-01-05"),
                },
            ],
            "dimensionless",
            pd.Timedelta("1h"),
            "mean",
            pd.Series(
                [1] * 24 * 2 + [1.5] * 24 + [2] * 24,
                index=pd.date_range(
                    "2023-01-01", "2023-01-05", freq="1h", inclusive="left"
                ),
                name="event_value",
            ),
        ),
        # Test case 3: Handling Quantity values with first
        (
            pd.date_range("2023-01-01", "2023-01-05", freq="1h", inclusive="left"),
            [
                {
                    "value": ur.Quantity(1, "m"),
                    "start": pd.Timestamp("2023-01-01"),
                    "end": pd.Timestamp("2023-01-04"),
                },
                {
                    "value": ur.Quantity(2, "m"),
                    "start": pd.Timestamp("2023-01-03"),
                    "end": pd.Timestamp("2023-01-05"),
                },
            ],
            "km",
            pd.Timedelta("1h"),
            "first",
            pd.Series(
                [0.001] * 24 * 3 + [0.002] * 24,
                index=pd.date_range(
                    "2023-01-01", "2023-01-05", freq="1h", inclusive="left"
                ),
                name="event_value",
            ),
        ),
        # Test case 4: switch order of segments in list, with respect to test case 3
        (
            pd.date_range("2023-01-01", "2023-01-05", freq="1h", inclusive="left"),
            [
                {
                    "value": ur.Quantity(2, "m"),
                    "start": pd.Timestamp("2023-01-03"),
                    "end": pd.Timestamp("2023-01-05"),
                },
                {
                    "value": ur.Quantity(1, "m"),
                    "start": pd.Timestamp("2023-01-01"),
                    "end": pd.Timestamp("2023-01-04"),
                },
            ],
            "km",
            pd.Timedelta("1h"),
            "first",
            pd.Series(
                [0.001] * 24 * 2 + [0.002] * 24 * 2,
                index=pd.date_range(
                    "2023-01-01", "2023-01-05", freq="1h", inclusive="left"
                ),
                name="event_value",
            ),
        ),
    ],
)
def test_process_time_series_segments(
    index, variable_quantity, unit, resolution, resolve_overlaps, expected
):
    result = process_time_series_segments(
        index, variable_quantity, unit, resolution, resolve_overlaps
    )
    pd.testing.assert_series_equal(result, expected, check_dtype=False)
