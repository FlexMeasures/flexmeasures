import sys
import pytest

from datetime import datetime
from pytz import utc

from flexmeasures.cli import is_running as cli_is_running


def test_cli_is_running(app, monkeypatch):
    assert cli_is_running() is False
    monkeypatch.setattr(
        sys, "argv", ["/bin/flexmeasures", "add", "account", "--name", "XCorp."]
    )
    assert cli_is_running() is True


@pytest.mark.parametrize(
    "now, flag, expected_start, expected_end",
    [
        (
            datetime(2023, 4, 4, 1, 30, tzinfo=utc),
            "last_hour",
            datetime(2023, 4, 4, 0, tzinfo=utc),
            datetime(2023, 4, 4, 1, tzinfo=utc),
        ),
        (
            datetime(2023, 4, 4, 1, 30, tzinfo=utc),
            "last_day",
            datetime(2023, 4, 3, 0, tzinfo=utc),
            datetime(2023, 4, 4, 0, tzinfo=utc),
        ),
        (
            datetime(2023, 4, 8, 1, 30, tzinfo=utc),
            "last_7_days",
            datetime(2023, 4, 1, 0, tzinfo=utc),
            datetime(2023, 4, 8, 0, tzinfo=utc),
        ),
        (
            datetime(2023, 4, 8, 1, 30, tzinfo=utc),
            "last_month",
            datetime(2023, 3, 1, 0, tzinfo=utc),
            datetime(2023, 4, 1, 0, tzinfo=utc),
        ),
        (
            datetime(2023, 1, 1, tzinfo=utc),
            "last_month",
            datetime(2022, 12, 1, tzinfo=utc),
            datetime(2023, 1, 1, tzinfo=utc),
        ),
        (
            datetime(2023, 1, 2, tzinfo=utc),
            "last_year",
            datetime(2022, 1, 1, tzinfo=utc),
            datetime(2023, 1, 1, tzinfo=utc),
        ),
    ],
)
def test_get_timerange_from_flag(monkeypatch, now, flag, expected_start, expected_end):
    import flexmeasures.utils.time_utils as time_utils
    from flexmeasures.cli.utils import get_timerange_from_flag

    # mock server_now to `now`
    monkeypatch.setattr(time_utils, "server_now", lambda: now)

    input_arguments = {flag: True, "timezone": utc}

    start, end = get_timerange_from_flag(**input_arguments)

    assert start == expected_start
    assert end == expected_end
