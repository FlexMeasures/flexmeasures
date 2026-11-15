"""Tests for repeating posted sensor data, in dry runs, which never write (see the fresh-db module for saving repeated values)."""

from __future__ import annotations

from datetime import timedelta

from flask import current_app, url_for
import pandas as pd
import pytest
from sqlalchemy import func, select

from flexmeasures import Sensor, Source
from flexmeasures.data.models.time_series import TimedBelief


@pytest.fixture(scope="module")
def soc_sensors(db, setup_api_test_data) -> dict[str, Sensor]:
    """Add an hourly SoC-minima sensor in Amsterdam and one on Lord Howe Island, next to the API test sensors."""
    asset = setup_api_test_data["some gas sensor"].generic_asset
    sensors = {
        name: Sensor(
            name=f"soc minima ({name})",
            unit="kWh",
            event_resolution=timedelta(hours=1),
            timezone=tz,
            generic_asset=asset,
        )
        for name, tz in (
            ("hours", "Europe/Amsterdam"),
            ("lord howe", "Australia/Lord_Howe"),
        )
    }
    db.session.add_all(sensors.values())
    db.session.flush()
    return sensors


def post(client, sensor: Sensor, **body):
    """Post the given body to the sensor's data endpoint."""
    response = client.post(url_for("SensorAPI:post_data", id=sensor.id), json=body)
    print(f"Server responded with:\n{response.json}")
    return response


def as_series(chunks: list[dict], resolution: timedelta) -> pd.Series:
    """Read the regular series of a dry run back into values indexed by event start."""
    return pd.concat(
        [
            pd.Series(
                chunk["values"],
                index=pd.date_range(
                    pd.Timestamp(chunk["start"]),
                    periods=len(chunk["values"]),
                    freq=resolution,
                ),
                dtype=float,
            )
            for chunk in chunks
        ]
    )


@pytest.mark.parametrize(
    "requesting_user", ["test_supplier_user_4@seita.nl"], indirect=True
)
def test_dry_run_daily(client, db, soc_sensors, requesting_user):
    """Repeat a pattern with a gap in it daily, starting with the pattern itself, and check nothing is written."""
    sensor = soc_sensors["hours"]
    n_beliefs = db.session.scalar(select(func.count()).select_from(TimedBelief))
    n_sources = db.session.scalar(select(func.count()).select_from(Source))

    response = post(
        client,
        sensor,
        start="2026-06-01T06:00+02:00",
        duration="PT3H",
        values=[80, None, 90],
        unit="kWh",
        repeat="daily",
        until="2026-06-02",
        **{"dry-run": True},
    )

    assert response.status_code == 200
    assert response.json["data"] == [
        dict(
            start="2026-06-01T06:00:00+02:00",
            duration="PT27H",
            values=[80, None, 90] + 21 * [None] + [80, None, 90],
            unit="kWh",
        )
    ]
    report = response.json["report"]
    assert report["n-values"] == 4
    assert report["n-occurrences"] == 1
    assert report["pattern-included"] is True
    assert report["period"] == "daily"
    assert report["transitions"] == []
    assert "mode" not in report
    assert db.session.scalar(select(func.count()).select_from(TimedBelief)) == n_beliefs
    assert db.session.scalar(select(func.count()).select_from(Source)) == n_sources


@pytest.mark.parametrize(
    "requesting_user", ["test_supplier_user_4@seita.nl"], indirect=True
)
def test_dry_run_without_repeat(client, soc_sensors, requesting_user):
    """A dry run of plain posted data echoes what would be saved, without a report."""
    response = post(
        client,
        soc_sensors["hours"],
        start="2026-06-01T06:00+02:00",
        duration="PT2H",
        values=[80, 90],
        unit="kWh",
        **{"dry-run": True},
    )

    assert response.status_code == 200
    assert response.json["data"] == [
        dict(
            start="2026-06-01T06:00:00+02:00",
            duration="PT2H",
            values=[80, 90],
            unit="kWh",
        )
    ]
    assert "report" not in response.json


@pytest.mark.parametrize(
    "requesting_user", ["test_supplier_user_4@seita.nl"], indirect=True
)
def test_dry_run_same_weekday(client, soc_sensors, requesting_user):
    """Repeat a pattern longer than a day on the same weekday, upsampled to the sensor resolution."""
    response = post(
        client,
        soc_sensors["hours"],
        start="2026-06-01T23:00+02:00",  # a Monday
        duration="PT2H",
        values=60,  # one value for two hours
        unit="kWh",
        repeat="same-weekday",
        until="2026-06-15",
        horizon="PT0H",
        **{"dry-run": True},
    )

    assert response.status_code == 200
    (data,) = response.json["data"]
    assert data["start"] == "2026-06-01T23:00:00+02:00"
    # Only the first hour of the last repeat starts on June 15.
    assert data["values"] == [60, 60] + (7 * 24 - 2) * [None] + [60, 60] + (
        7 * 24 - 2
    ) * [None] + [60]
    assert response.json["report"]["period"] == "weekly"
    assert response.json["report"]["n-values"] == 5


@pytest.mark.parametrize(
    "start, repeat, expected_days, pattern_included",
    [
        ("2026-06-05T06:00+02:00", "workdays", [5, 8, 9, 10, 11, 12, 15], True),
        ("2026-06-05T06:00+02:00", "weekends", [6, 7, 13, 14], False),
        # A Saturday pattern on workdays is left out, so the first value is on Monday.
        ("2026-06-06T06:00+02:00", "workdays", [8, 9, 10, 11, 12, 15], False),
    ],
)
@pytest.mark.parametrize(
    "requesting_user", ["test_supplier_user_4@seita.nl"], indirect=True
)
def test_dry_run_on_some_days_only(
    client, soc_sensors, requesting_user, start, repeat, expected_days, pattern_included
):
    """Repeat a pattern on workdays or weekends only, which includes the pattern only if its own day is one of them."""
    response = post(
        client,
        soc_sensors["hours"],
        start=start,
        duration="PT1H",
        values=[50],
        unit="kWh",
        repeat=repeat,
        until="2026-06-15",  # a Monday
        **{"dry-run": True},
    )

    assert response.status_code == 200
    values = as_series(response.json["data"], timedelta(hours=1)).dropna()
    assert [t.day for t in values.index] == expected_days
    assert (values.index.hour == 6).all()
    report = response.json["report"]
    assert report["pattern-included"] is pattern_included
    assert report["n-occurrences"] == len(expected_days) - pattern_included


@pytest.mark.parametrize(
    "fall_back, expected_report",
    [
        (
            False,
            dict(kind="spring-forward", omitted=["02:00"], duplicated=[]),
        ),
        (
            True,
            dict(kind="fall-back", omitted=[], duplicated=["02:00"]),
        ),
    ],
)
@pytest.mark.parametrize(
    "requesting_user", ["test_supplier_user_4@seita.nl"], indirect=True
)
def test_dry_run_across_dst(
    client, soc_sensors, requesting_user, fall_back, expected_report
):
    """Repeat a day of hourly values onto a day of 23 or 25 hours, and check the report says which hour was omitted or duplicated."""
    response = post(
        client,
        soc_sensors["hours"],
        start="2026-10-24T00:00+02:00" if fall_back else "2026-03-28T00:00+01:00",
        duration="P1D",
        values=list(range(24)),
        unit="kWh",
        repeat="daily",
        until="2026-10-25" if fall_back else "2026-03-29",
        **{"dry-run": True},
    )

    assert response.status_code == 200
    (data,) = response.json["data"]
    values = data["values"]
    if fall_back:
        # The value for 02:00 is repeated to both instants of 02:00.
        assert values == list(range(24)) + [0, 1, 2, 2] + list(range(3, 24))
    else:
        # There is no 02:00 to repeat the value for 02:00 to.
        assert values == list(range(24)) + [0, 1] + list(range(3, 24))
    report = response.json["report"]
    assert report["n-values"] == len(values)
    assert report["n-omitted"] == len(expected_report["omitted"])
    assert report["n-duplicated"] == len(expected_report["duplicated"])
    assert report["n-transitions-checked"] == 1
    (transition,) = report["transitions"]
    for key, value in expected_report.items():
        assert transition[key] == value


@pytest.mark.parametrize(
    "requesting_user", ["test_supplier_user_4@seita.nl"], indirect=True
)
def test_dry_run_lists_only_transitions_with_an_effect(
    client, soc_sensors, requesting_user
):
    """A daily pattern that leaves out the night is not affected by the fall-back, which is then only counted as checked."""
    response = post(
        client,
        soc_sensors["hours"],
        start="2026-10-24T06:00+02:00",
        duration="PT2H",
        values=[80, 90],
        unit="kWh",
        repeat="daily",
        until="2026-10-26",
        **{"dry-run": True},
    )

    assert response.status_code == 200
    report = response.json["report"]
    assert report["n-transitions-checked"] == 1
    assert report["transitions"] == []


@pytest.mark.parametrize(
    "requesting_user", ["test_supplier_user_4@seita.nl"], indirect=True
)
def test_dry_run_stays_on_the_local_hour_on_lord_howe_island(
    client, soc_sensors, requesting_user
):
    """Hourly values keep starting on the local hour across a 30-minute fall-back, with one extra event filling the repeated half hour."""
    response = post(
        client,
        soc_sensors["lord howe"],
        start="2026-04-04T00:00+11:00",
        duration="P1D",
        values=list(range(24)),
        unit="kWh",
        repeat="daily",
        until="2026-04-05",
        **{"dry-run": True},
    )

    assert response.status_code == 200
    # The extra event breaks the regular series, so the values come in more than one part.
    data = response.json["data"]
    assert len(data) > 1
    starts = pd.DatetimeIndex(
        [
            pd.Timestamp(chunk["start"]) + i * pd.Timedelta(hours=1)
            for chunk in data
            for i in range(len(chunk["values"]))
        ]
    ).tz_convert("Australia/Lord_Howe")
    values = [v for chunk in data for v in chunk["values"]]
    by_start = dict(zip(starts, values))
    assert by_start[pd.Timestamp("2026-04-05T01:00+11:00")] == 1
    assert by_start[pd.Timestamp("2026-04-05T01:30+11:00")] == 1
    assert by_start[pd.Timestamp("2026-04-05T02:00+10:30")] == 2
    assert (starts[starts >= pd.Timestamp("2026-04-05T02:00+10:30")].minute == 0).all()
    (transition,) = response.json["report"]["transitions"]
    assert transition["duplicated"] == ["01:00"]


@pytest.mark.parametrize(
    "requesting_user, status_code",
    [
        (None, 401),
        # Authenticated, but not a member of the organisation that owns the sensor.
        ("test_dummy_user_3@seita.nl", 403),
        # Same organisation, but allowed to read data only.
        ("test_supplier_reader@seita.nl", 403),
    ],
    indirect=["requesting_user"],
)
def test_dry_run_requires_permission_to_post_data(
    client, soc_sensors, setup_supplier_account_reader, requesting_user, status_code
):
    response = post(
        client,
        soc_sensors["hours"],
        start="2026-06-01T06:00+02:00",
        duration="PT1H",
        values=[80],
        unit="kWh",
        repeat="daily",
        until="2026-06-03",
        **{"dry-run": True},
    )
    assert response.status_code == status_code


@pytest.mark.parametrize(
    "sensor_key, changes, error_text",
    [
        (
            "hours",
            dict(duration="PT25H", values=25 * [80]),
            "longer than the recurrence period",
        ),
        ("hours", dict(until="2027-06-02"), "Repeat until 2027-06-01 at the latest"),
        ("hours", dict(until="2026-05-31"), "repeat them until a later date"),
        ("hours", dict(duration="PT1H", values=[80, 90]), "or coarser"),
        ("hours", dict(unit="°C"), "Required unit"),
        ("hours", dict(repeat="weekly"), "Must be one of"),
        ("hours", dict(duration="P1M"), "rather than in months or years"),
        ("hours", dict(until=None), "Give both `repeat` and `until`"),
        ("temperature", dict(unit="°C"), "instantaneous values"),
    ],
)
@pytest.mark.parametrize("dry_run", [True, False])
@pytest.mark.parametrize(
    "requesting_user", ["test_supplier_user_4@seita.nl"], indirect=True
)
def test_repeat_refuses_invalid_patterns(
    client,
    setup_api_test_data,
    soc_sensors,
    requesting_user,
    dry_run,
    sensor_key,
    changes,
    error_text,
):
    """A dry run and a real post refuse the same patterns."""
    sensors = {
        **soc_sensors,
        "temperature": setup_api_test_data["some temperature sensor"],
    }
    body = dict(
        start="2026-06-01T06:00+02:00",
        duration="PT1H",
        values=[80],
        unit="kWh",
        repeat="daily",
        until="2026-06-03",
    )
    body.update(changes)
    body = {key: value for key, value in body.items() if value is not None}

    response = post(client, sensors[sensor_key], **body, **{"dry-run": dry_run})

    assert response.status_code == 422
    assert error_text in str(response.json["message"])


@pytest.mark.parametrize(
    "requesting_user", ["test_supplier_user_4@seita.nl"], indirect=True
)
def test_repeat_refuses_more_values_than_allowed(
    client, soc_sensors, requesting_user, monkeypatch
):
    """The request stays small however far it repeats, so the number of values it expands to is capped."""
    monkeypatch.setitem(
        current_app.config, "FLEXMEASURES_MAX_REPEATED_SENSOR_VALUES", 48
    )
    body = dict(
        start="2026-06-01T00:00+02:00",
        duration="P1D",
        values=24 * [80],
        unit="kWh",
        repeat="daily",
        **{"dry-run": True},
    )

    response = post(client, soc_sensors["hours"], until="2026-06-02", **body)
    assert response.status_code == 200

    response = post(client, soc_sensors["hours"], until="2026-06-03", **body)
    assert response.status_code == 422
    assert "Repeating gives 72 values, more than the maximum of 48" in str(
        response.json["message"]
    )
