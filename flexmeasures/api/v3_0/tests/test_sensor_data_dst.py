"""GET /sensors/<id>/data for a daily sensor, over a daylight saving time change."""

from __future__ import annotations

from datetime import timedelta

from flask import url_for
import pandas as pd
import pytest

from flexmeasures import Sensor, User
from flexmeasures.data.models.time_series import TimedBelief

DAYS = pd.date_range("2026-10-20", "2026-11-17", freq="D", tz="Europe/Amsterdam")


@pytest.fixture(scope="module")
def daily_sensor_across_dst_end(db, setup_api_test_data, setup_roles_users) -> Sensor:
    """A daily sensor in Europe/Amsterdam, with a figure for every local day from 20 October to 17 November 2026.

    Daylight saving time ends on 25 October 2026, so that day lasts 25 hours.
    """
    gas_sensor = setup_api_test_data["some gas sensor"]
    sensor = Sensor(
        name="daily earnings",
        unit="EUR",
        event_resolution=timedelta(days=1),
        timezone="Europe/Amsterdam",
        generic_asset=gas_sensor.generic_asset,
    )
    db.session.add(sensor)
    source = db.session.get(User, setup_roles_users["Test Supplier User"]).data_source[
        0
    ]
    db.session.add_all(
        [
            TimedBelief(
                sensor=sensor,
                source=source,
                event_start=day,
                belief_horizon=timedelta(0),
                event_value=float(i),
            )
            for i, day in enumerate(DAYS)
        ]
    )
    db.session.flush()
    return sensor


@pytest.mark.parametrize(
    "start, duration, resolution, expected",
    [
        # The case found from Home Assistant: a window opened before the 25-hour day
        (
            "2026-10-20T00:00:00+02:00",
            "P29D",
            "P1D",
            [float(i) for i in range(len(DAYS))],
        ),
        # Same, leaving out the resolution (the sensor's own one is used)
        (
            "2026-10-20T00:00:00+02:00",
            "P29D",
            None,
            [float(i) for i in range(len(DAYS))],
        ),
        # Same window, opened in UTC
        (
            "2026-10-19T22:00:00+00:00",
            "P29D",
            "P1D",
            [float(i) for i in range(len(DAYS))],
        ),
        # A window given in hours (fixed), so the window question is out of the way:
        # 20 October 00:00+02:00 + 697 hours = 18 November 00:00+01:00
        (
            "2026-10-20T00:00:00+02:00",
            "PT697H",
            "P1D",
            [float(i) for i in range(len(DAYS))],
        ),
        # A window that only starts after the change works today (Home Assistant's second request)
        (
            "2026-11-01T00:00:00+01:00",
            "P17D",
            "P1D",
            [float(i) for i in range(12, len(DAYS))],
        ),
    ],
)
@pytest.mark.parametrize(
    "requesting_user", ["test_supplier_user_4@seita.nl"], indirect=True
)
def test_get_daily_sensor_data_across_dst_end(
    client,
    daily_sensor_across_dst_end: Sensor,
    requesting_user,
    start,
    duration,
    resolution,
    expected,
):
    """Daily figures on both sides of a DST change come back in one request.

    The days after 25 October start at 00:00+01:00, not at 00:00+02:00,
    so a grid of fixed 24-hour steps from the request's +02:00 start misses every one of them.
    """
    message = {"start": start, "duration": duration, "unit": "EUR"}
    if resolution:
        message["resolution"] = resolution
    response = client.get(
        url_for("SensorAPI:get_data", id=daily_sensor_across_dst_end.id),
        query_string=message,
    )
    print("Server responded with:\n%s" % response.json)
    assert response.status_code == 200
    assert response.json["values"] == expected
