from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest
import pytz
import timely_beliefs as tb

from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.time_series import Sensor, TimedBelief
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
def test_collect_power(db, app, query_start, query_end, num_values, setup_test_data):
    wind_device_1 = Sensor.query.filter_by(name="wind-asset-1").one_or_none()
    data = TimedBelief.query.filter(TimedBelief.sensor_id == wind_device_1.id).all()
    print(data)
    bdf: tb.BeliefsDataFrame = TimedBelief.search(
        wind_device_1.name,
        event_starts_after=query_start,
        event_ends_before=query_end,
    )
    print(bdf)
    assert (
        bdf.index.names[0] == "event_start"
    )  # first index level of collect function should be event_start, so that df.loc[] refers to event_start
    assert pd.api.types.is_timedelta64_dtype(
        bdf.convert_index_from_belief_time_to_horizon().index.get_level_values(
            "belief_horizon"
        )
    )  # dtype of belief_horizon is timedelta64[ns], so the minimum horizon on an empty BeliefsDataFrame is NaT instead of NaN
    assert len(bdf) == num_values
    for v1, v2 in zip(bdf["event_value"].tolist(), data):
        assert abs(v1 - v2.event_value) < 10 ** -6


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
def tesfijfijft_collect_power_resampled(
    db, app, query_start, query_end, resolution, num_values, setup_test_data
):
    wind_device_1 = Sensor.query.filter_by(name="wind-asset-1").one_or_none()
    bdf: tb.BeliefsDataFrame = TimedBelief.search(
        wind_device_1.name,
        event_starts_after=query_start,
        event_ends_before=query_end,
        resolution=resolution,
        most_recent_beliefs_only=True,
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


@pytest.mark.parametrize("check_empty_frame", [True, False])
def test_simplify_index(setup_test_data, check_empty_frame):
    """Check whether simplify_index retains the event resolution."""
    wind_device_1 = Sensor.query.filter_by(name="wind-asset-1").one_or_none()
    bdf: tb.BeliefsDataFrame = TimedBelief.search(
        wind_device_1.name,
        event_starts_after=datetime(2015, 1, 1, tzinfo=pytz.utc),
        event_ends_before=datetime(2015, 1, 2, tzinfo=pytz.utc),
        resolution=timedelta(minutes=15),
    ).convert_index_from_belief_time_to_horizon()
    if check_empty_frame:
        # We empty the BeliefsDataFrame, which retains the metadata such as sensor and resolution
        bdf = bdf.iloc[0:0, :]
    df = simplify_index(bdf)
    assert df.event_resolution == timedelta(minutes=15)


def test_query_beliefs(setup_beliefs):
    """Check various ways of querying for beliefs."""
    sensor = Sensor.query.filter_by(name="epex_da").one_or_none()
    source = DataSource.query.filter_by(name="ENTSO-E").one_or_none()
    bdfs = [
        TimedBelief.search(sensor, source=source, most_recent_beliefs_only=False),
        TimedBelief.search(sensor.id, source=source, most_recent_beliefs_only=False),
        TimedBelief.search(sensor.name, source=source, most_recent_beliefs_only=False),
        sensor.search_beliefs(source=source, most_recent_beliefs_only=False),
        tb.BeliefsDataFrame(sensor.beliefs)[
            tb.BeliefsDataFrame(sensor.beliefs).index.get_level_values("source")
            == source
        ],
    ]
    for bdf in bdfs:
        assert sensor.event_resolution == timedelta(hours=1)
        assert bdf.event_resolution == timedelta(hours=1)
        assert len(bdf) == setup_beliefs


def test_persist_beliefs(setup_beliefs, setup_test_data):
    """Check whether persisting beliefs works.

    We load the already set up beliefs, and form new beliefs an hour later.
    """
    sensor = Sensor.query.filter_by(name="epex_da").one_or_none()
    source = DataSource.query.filter_by(name="ENTSO-E").one_or_none()
    bdf: tb.BeliefsDataFrame = TimedBelief.search(
        sensor, source=source, most_recent_beliefs_only=False
    )

    # Form new beliefs
    df = bdf.reset_index()
    df["belief_time"] = df["belief_time"] + timedelta(hours=1)
    df["event_value"] = df["event_value"] * 10
    bdf = df.set_index(
        ["event_start", "belief_time", "source", "cumulative_probability"]
    )

    TimedBelief.add(bdf)
    bdf: tb.BeliefsDataFrame = TimedBelief.search(
        sensor, source=source, most_recent_beliefs_only=False
    )
    assert len(bdf) == setup_beliefs * 2
