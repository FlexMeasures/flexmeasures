from datetime import datetime, timedelta

from isodate import duration_isoformat as original_duration_isoformat
import pandas as pd
import pytz
import pytest

from flexmeasures.utils.time_utils import (
    duration_isoformat,
    server_now,
    naturalized_datetime_str,
    get_most_recent_clocktime_window,
)


@pytest.mark.parametrize(
    "td, iso",
    [
        (timedelta(hours=1), "PT1H"),
        (timedelta(hours=14), "PT14H"),
        (timedelta(hours=24), "PT24H"),
        (timedelta(days=1), "PT24H"),
        (timedelta(days=1, seconds=22), "PT24H22S"),
        (timedelta(days=1, seconds=122), "PT24H2M2S"),
    ],
)
def test_duration_isoformat(td: timedelta, iso: str):
    assert duration_isoformat(td) == iso


@pytest.mark.parametrize(
    "td, iso",
    [
        (timedelta(hours=1), "PT1H"),
        (timedelta(hours=14), "PT14H"),
        # todo: if the following test cases fail, we can start using isodate.duration_isoformat again (see #459)
        (timedelta(hours=24), "P1D"),
        (timedelta(days=1), "P1D"),
        (timedelta(days=1, seconds=22), "P1DT22S"),
        (timedelta(days=1, seconds=122), "P1DT2M2S"),
    ],
)
def test_original_duration_isoformat(td: timedelta, iso: str):
    assert original_duration_isoformat(td) == iso


@pytest.mark.parametrize(
    "dt_tz, now, server_tz, delta_in_h, exp_result",
    # there can be two results depending of today's date, due to humanize.
    # Monekypatching was too hard.
    [
        (None, pd.Timestamp.utcnow(), "UTC", 3, "3 hours ago"),
        (None, pd.Timestamp.utcnow().tz_convert("Asia/Seoul"), "UTC", 3, "3 hours ago"),
        (None, datetime.utcnow(), "UTC", 3, "3 hours ago"),
        (
            None,
            datetime(2021, 5, 17, 3),
            "Europe/Amsterdam",
            48,
            ("May 15", "May 15 2021"),
        ),
        ("Asia/Seoul", "server_now", "Europe/Amsterdam", 1, "an hour ago"),
        (
            "UTC",
            datetime(2021, 5, 17, 3),
            "Asia/Seoul",
            24 * 7,
            ("May 10", "May 10 2021"),
        ),
        ("UTC", datetime(2021, 5, 17, 3), "Asia/Seoul", None, "never"),
    ],
)
def test_naturalized_datetime_str(
    app,
    monkeypatch,
    dt_tz,
    now,
    server_tz,
    delta_in_h,
    exp_result,
):
    monkeypatch.setitem(app.config, "FLEXMEASURES_TIMEZONE", server_tz)
    if now == "server_now":
        now = server_now()  # done this way as it needs (patched) app context
    if now.tzinfo is None:
        now = now.replace(tzinfo=pytz.utc)  # assuming UTC
    if delta_in_h is not None:
        h_ago = now - timedelta(hours=delta_in_h)
        if dt_tz is not None:
            h_ago = h_ago.astimezone(pytz.timezone(dt_tz))
    else:
        h_ago = None
    if isinstance(exp_result, tuple):
        assert naturalized_datetime_str(h_ago, now=now) in exp_result
    else:
        assert naturalized_datetime_str(h_ago, now=now) == exp_result


@pytest.mark.parametrize(
    "window_size, now, exp_start, exp_end",
    [
        (
            5,
            datetime(2021, 4, 30, 15, 1),
            datetime(2021, 4, 30, 14, 55),
            datetime(2021, 4, 30, 15),
        ),
        (
            15,
            datetime(2021, 4, 30, 3, 36),
            datetime(2021, 4, 30, 3, 15),
            datetime(2021, 4, 30, 3, 30),
        ),
        (
            10,
            datetime(2021, 4, 30, 0, 5),
            datetime(2021, 4, 29, 23, 50),
            datetime(2021, 4, 30, 0, 0),
        ),
        (
            5,
            datetime(2021, 5, 20, 10, 5, 34),  # boundary condition
            datetime(2021, 5, 20, 9, 55),
            datetime(2021, 5, 20, 10, 0),
        ),
        (
            60,
            datetime(2021, 1, 1, 0, 4),  # new year
            datetime(2020, 12, 31, 23, 00),
            datetime(2021, 1, 1, 0, 0),
        ),
        (
            60,
            datetime(2021, 3, 28, 3, 10),  # DST transition
            datetime(2021, 3, 28, 2),
            datetime(2021, 3, 28, 3),
        ),
    ],
)
def test_recent_clocktime_window(window_size, now, exp_start, exp_end):
    start, end = get_most_recent_clocktime_window(window_size, now=now)
    assert start == exp_start
    assert end == exp_end


def test_recent_clocktime_window_invalid_window():
    with pytest.raises(AssertionError):
        get_most_recent_clocktime_window(25, now=datetime(2021, 4, 30, 3, 36))
        get_most_recent_clocktime_window(120, now=datetime(2021, 4, 30, 3, 36))
        get_most_recent_clocktime_window(0, now=datetime(2021, 4, 30, 3, 36))
