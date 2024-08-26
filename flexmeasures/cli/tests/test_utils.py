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


def test_get_unique_sensor_names(app, db, add_asset_with_children):
    from flexmeasures.cli.utils import get_sensor_aliases
    from flexmeasures.cli.data_show import find_duplicates

    sensors = []
    for assets in add_asset_with_children.values():
        for asset in assets.values():
            sensors.extend(asset.sensors)

    duplicates = find_duplicates(sensors, "name")
    aliases = get_sensor_aliases(sensors, duplicates)
    expected_aliases = [
        "power (Test Supplier Account/parent/child_1)",
        "power (Test Supplier Account/parent/child_2)",
        "power (Test Supplier Account/parent)",
        "power (Test Dummy Account/parent/child_1)",
        "power (Test Dummy Account/parent/child_2)",
        "power (Test Dummy Account/parent)",
    ]

    assert list(aliases.values()) == expected_aliases

    duplicates = find_duplicates(sensors, "name")
    aliases = get_sensor_aliases(sensors[:2], duplicates)
    expected_aliases = [
        "power (child_1)",
        "power (child_2)",
    ]

    assert list(aliases.values()) == expected_aliases

    duplicates = find_duplicates(sensors, "name")
    aliases = get_sensor_aliases(sensors[:3], duplicates)
    expected_aliases = [
        "power (parent/child_1)",
        "power (parent/child_2)",
        "power (parent)",
    ]

    assert list(aliases.values()) == expected_aliases
