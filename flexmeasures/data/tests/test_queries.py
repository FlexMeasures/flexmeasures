from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest
import pytz
import timely_beliefs as tb

from flexmeasures.data.models.assets import Asset, Power
from flexmeasures.data.queries.utils import (
    multiply_dataframe_with_deterministic_beliefs,
    simplify_index,
)


@pytest.mark.parametrize(
    "query_start, query_end, num_values",
    [
        (
            datetime(2015, 1, 1, tzinfo=pytz.utc),
            datetime(2015, 1, 2, tzinfo=pytz.utc),
            96,
        ),
        (datetime(2015, 1, 1, tzinfo=pytz.utc), None, 96),
        (None, datetime(2015, 1, 2, tzinfo=pytz.utc), 96),
        (None, None, 96),
        (
            datetime(2015, 1, 1, tzinfo=pytz.utc),
            datetime(2015, 1, 1, 12, tzinfo=pytz.utc),
            48,
        ),
        (None, datetime(2015, 1, 1, 12, tzinfo=pytz.utc), 48),
        # (
        #     datetime(1957, 1, 1, tzinfo=pytz.utc),
        #     datetime(1957, 1, 2, tzinfo=pytz.utc),
        #     0,
        # ),  # test empty BeliefsDataFrame  # todo: uncomment when this if fixed: https://github.com/pandas-dev/pandas/issues/30517
    ],
)
def test_collect_power(db, app, query_start, query_end, num_values):
    wind_device_1 = Asset.query.filter_by(name="wind-asset-1").one_or_none()
    data = Power.query.filter(Power.asset_id == wind_device_1.id).all()
    print(data)
    bdf: tb.BeliefsDataFrame = Power.collect(
        wind_device_1.name, (query_start, query_end)
    )
    print(bdf)
    assert (
        bdf.index.names[0] == "event_start"
    )  # first index level of collect function should be event_start, so that df.loc[] refers to event_start
    assert pd.api.types.is_timedelta64_dtype(
        bdf.index.get_level_values("belief_horizon")
    )  # dtype of belief_horizon is timedelta64[ns], so the minimum horizon on an empty BeliefsDataFrame is NaT instead of NaN
    assert len(bdf) == num_values
    for v1, v2 in zip(bdf.values, data):
        assert abs(v1[0] - v2.value) < 10 ** -6


@pytest.mark.parametrize(
    "query_start, query_end, resolution, num_values",
    [
        (
            datetime(2015, 1, 1, tzinfo=pytz.utc),
            datetime(2015, 1, 2, tzinfo=pytz.utc),
            timedelta(minutes=15),
            96,
        ),
        (
            datetime(2015, 1, 1, tzinfo=pytz.utc),
            datetime(2015, 1, 2, tzinfo=pytz.utc),
            timedelta(minutes=30),
            48,
        ),
        (
            datetime(2015, 1, 1, tzinfo=pytz.utc),
            datetime(2015, 1, 2, tzinfo=pytz.utc),
            "30min",
            48,
        ),
        (
            datetime(2015, 1, 1, tzinfo=pytz.utc),
            datetime(2015, 1, 2, tzinfo=pytz.utc),
            "PT45M",
            32,
        ),
    ],
)
def test_collect_power_resampled(
    db, app, query_start, query_end, resolution, num_values
):
    wind_device_1 = Asset.query.filter_by(name="wind-asset-1").one_or_none()
    bdf: tb.BeliefsDataFrame = Power.collect(
        wind_device_1.name, (query_start, query_end), resolution=resolution
    )
    print(bdf)
    assert len(bdf) == num_values


def test_multiplication():
    df1 = pd.DataFrame(
        [[30.0, timedelta(hours=3)]],
        index=pd.date_range(
            "2000-01-01 10:00", "2000-01-01 15:00", freq="1h", closed="left"
        ),
        columns=["event_value", "belief_horizon"],
    )
    df2 = pd.DataFrame(
        [[10.0, timedelta(hours=1)]],
        index=pd.date_range(
            "2000-01-01 13:00", "2000-01-01 18:00", freq="1h", closed="left"
        ),
        columns=["event_value", "belief_horizon"],
    )
    df = multiply_dataframe_with_deterministic_beliefs(df1, df2)
    df_compare = pd.concat(
        [
            pd.DataFrame(
                [[np.nan, timedelta(hours=3)]],
                index=pd.date_range(
                    "2000-01-01 10:00", "2000-01-01 13:00", freq="1h", closed="left"
                ),
                columns=["event_value", "belief_horizon"],
            ),
            pd.DataFrame(
                [[300.0, timedelta(hours=1)]],
                index=pd.date_range(
                    "2000-01-01 13:00", "2000-01-01 15:00", freq="1h", closed="left"
                ),
                columns=["event_value", "belief_horizon"],
            ),
            pd.DataFrame(
                [[np.nan, timedelta(hours=1)]],
                index=pd.date_range(
                    "2000-01-01 15:00", "2000-01-01 18:00", freq="1h", closed="left"
                ),
                columns=["event_value", "belief_horizon"],
            ),
        ],
        axis=0,
    )
    pd.testing.assert_frame_equal(df, df_compare)


def test_multiplication_with_one_empty_dataframe():
    df1 = pd.DataFrame(
        [],
        columns=["event_value", "belief_horizon"],
    )
    # set correct types
    df1["event_value"] = pd.to_numeric(df1["event_value"])
    df1["belief_horizon"] = pd.to_timedelta(df1["belief_horizon"])

    df2 = pd.DataFrame(
        [[10.0, timedelta(hours=1)]],
        index=pd.date_range(
            "2000-01-01 13:00", "2000-01-01 18:00", freq="1h", closed="left"
        ),
        columns=["event_value", "belief_horizon"],
    )

    df_compare = pd.DataFrame(
        [[np.nan, timedelta(hours=1)]],
        index=pd.date_range(
            "2000-01-01 13:00", "2000-01-01 18:00", freq="1h", closed="left"
        ),
        columns=["event_value", "belief_horizon"],
    )
    # set correct types
    df_compare["event_value"] = pd.to_numeric(df_compare["event_value"])
    df_compare["belief_horizon"] = pd.to_timedelta(df_compare["belief_horizon"])

    df = multiply_dataframe_with_deterministic_beliefs(df1, df2)
    pd.testing.assert_frame_equal(df, df_compare)


def test_multiplication_with_both_empty_dataframe():
    df1 = pd.DataFrame(
        [],
        columns=["event_value", "belief_horizon"],
    )
    # set correct types
    df1["event_value"] = pd.to_numeric(df1["event_value"])
    df1["belief_horizon"] = pd.to_timedelta(df1["belief_horizon"])

    df2 = pd.DataFrame(
        [],
        columns=["event_value", "belief_horizon"],
    )
    # set correct types
    df2["event_value"] = pd.to_numeric(df2["event_value"])
    df2["belief_horizon"] = pd.to_timedelta(df2["belief_horizon"])

    df_compare = pd.DataFrame(
        [],
        columns=["event_value", "belief_horizon"],
    )
    # set correct types
    df_compare["event_value"] = pd.to_numeric(df_compare["event_value"])
    df_compare["belief_horizon"] = pd.to_timedelta(df_compare["belief_horizon"])

    df = multiply_dataframe_with_deterministic_beliefs(df1, df2)
    pd.testing.assert_frame_equal(df, df_compare)


def test_simplify_index():
    """Check whether simplify_index retains the event resolution."""
    wind_device_1 = Asset.query.filter_by(name="wind-asset-1").one_or_none()
    bdf: tb.BeliefsDataFrame = Power.collect(
        wind_device_1.name,
        (
            datetime(2015, 1, 1, tzinfo=pytz.utc),
            datetime(2015, 1, 2, tzinfo=pytz.utc),
        ),
        resolution=timedelta(minutes=15),
    )
    df = simplify_index(bdf)
    assert df.event_resolution == timedelta(minutes=15)
