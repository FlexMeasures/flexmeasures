from datetime import datetime, timedelta

import pytest
import pytz
import timely_beliefs as tb

from bvp.data.models.assets import Asset, Power


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
