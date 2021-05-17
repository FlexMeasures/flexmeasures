from datetime import datetime, timedelta

import pytz
import pytest

from flexmeasures.utils.time_utils import (
    server_now,
    naturalized_datetime_str,
)


@pytest.mark.parametrize(
    "dt_tz,now,server_tz,delta_in_h,exp_result",
    [
        (None, datetime.utcnow(), "UTC", 3, "3 hours ago"),
        (None, datetime(2021, 5, 17, 3), "Europe/Amsterdam", 48, "May 15"),
        ("Asia/Seoul", "server_now", "Europe/Amsterdam", 1, "an hour ago"),
        ("UTC", datetime(2021, 5, 17, 3), "Asia/Seoul", 24 * 7, "May 10"),
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
        now = server_now()  # done this way as it needs app context
    if delta_in_h is not None:
        h_ago = datetime.utcnow() - timedelta(hours=delta_in_h)
        if dt_tz is not None:
            h_ago = h_ago.replace(tzinfo=pytz.utc).astimezone(pytz.timezone(dt_tz))
    else:
        h_ago = None
    print(h_ago)
    assert naturalized_datetime_str(h_ago, now=now) == exp_result
