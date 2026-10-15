"""Tests for previewing a repeated pattern of sensor values, which never writes (see the fresh-db module for saving the preview)."""

from __future__ import annotations

from datetime import timedelta

from flask import current_app, url_for
import pytest
from sqlalchemy import func, select

from flexmeasures import Sensor, Source
from flexmeasures.data.models.time_series import TimedBelief


@pytest.fixture(scope="module")
def soc_sensors(db, setup_api_test_data) -> dict[str, Sensor]:
    """Add an hourly and a daily SoC-minima sensor in Amsterdam, next to the API test sensors."""
    asset = setup_api_test_data["some gas sensor"].generic_asset
    sensors = {
        resolution: Sensor(
            name=f"soc minima ({resolution})",
            unit="kWh",
            event_resolution=timedelta(**{resolution: 1}),
            timezone="Europe/Amsterdam",
            generic_asset=asset,
        )
        for resolution in ("hours", "days")
    }
    db.session.add_all(sensors.values())
    db.session.flush()
    return sensors


def preview(client, sensor: Sensor, **pattern):
    """Preview the given pattern on the given sensor."""
    response = client.post(
        url_for("SensorAPI:preview_recurrence", id=sensor.id),
        json=pattern,
    )
    print(f"Server responded with:\n{response.json}")
    return response


@pytest.mark.parametrize(
    "requesting_user", ["test_supplier_user_4@seita.nl"], indirect=True
)
def test_preview_daily(client, db, soc_sensors, requesting_user):
    """Repeat a pattern with a gap in it daily, and check nothing is written."""
    sensor = soc_sensors["hours"]
    n_beliefs = db.session.scalar(select(func.count()).select_from(TimedBelief))
    n_sources = db.session.scalar(select(func.count()).select_from(Source))

    response = preview(
        client,
        sensor,
        start="2026-06-01T06:00+02:00",
        duration="PT3H",
        values=[80, None, 90],
        unit="kWh",
        repeat="daily",
        until="2026-06-03",
    )

    assert response.status_code == 200
    assert response.json["data"] == dict(
        start="2026-06-02T06:00:00+02:00",
        duration="PT27H",
        values=[80, None, 90] + 21 * [None] + [80, None, 90],
        unit="kWh",
    )
    report = response.json["report"]
    assert report["n_values"] == 4
    assert report["n_occurrences"] == 2
    assert report["period"] == "daily"
    assert report["mode"] == "wall_clock"
    assert report["transitions"] == []
    assert db.session.scalar(select(func.count()).select_from(TimedBelief)) == n_beliefs
    assert db.session.scalar(select(func.count()).select_from(Source)) == n_sources


@pytest.mark.parametrize(
    "requesting_user", ["test_supplier_user_4@seita.nl"], indirect=True
)
def test_preview_same_weekday(client, soc_sensors, requesting_user):
    """Repeat a pattern longer than a day on the same weekday, upsampled to the sensor resolution, and keep its belief timing."""
    sensor = soc_sensors["hours"]

    response = preview(
        client,
        sensor,
        start="2026-06-01T23:00+02:00",  # a Monday
        duration="PT2H",
        values=60,  # one value for two hours
        unit="kWh",
        repeat="same-weekday",
        until="2026-06-15",
        horizon="PT0H",
    )

    assert response.status_code == 200
    data = response.json["data"]
    assert data["start"] == "2026-06-08T23:00:00+02:00"
    # Only the first hour of the last repeat starts on June 15.
    assert data["values"] == [60, 60] + (7 * 24 - 2) * [None] + [60]
    assert data["horizon"] == "PT0H"
    assert response.json["report"]["period"] == "weekly"
    assert response.json["report"]["n_values"] == 3


@pytest.mark.parametrize(
    "fall_back, expected_report",
    [
        (
            False,
            dict(kind="spring_forward", omitted=["02:00"], duplicated=[]),
        ),
        (
            True,
            dict(kind="fall_back", omitted=[], duplicated=["02:00"]),
        ),
    ],
)
@pytest.mark.parametrize(
    "requesting_user", ["test_supplier_user_4@seita.nl"], indirect=True
)
def test_preview_across_dst(
    client, soc_sensors, requesting_user, fall_back, expected_report
):
    """Repeat a day of hourly values onto a day of 23 or 25 hours, and check the report says which hour was omitted or duplicated."""
    sensor = soc_sensors["hours"]
    day_before = "2026-10-23" if fall_back else "2026-03-27"

    response = preview(
        client,
        sensor,
        start=f"{day_before}T00:00{'+02:00' if fall_back else '+01:00'}",
        duration="P1D",
        values=list(range(24)),
        unit="kWh",
        repeat="daily",
        until="2026-10-25" if fall_back else "2026-03-29",
    )

    assert response.status_code == 200
    values = response.json["data"]["values"]
    if fall_back:
        # The value for 02:00 is repeated to both instants of 02:00.
        assert values == list(range(24)) + [0, 1, 2, 2] + list(range(3, 24))
    else:
        # There is no 02:00 to repeat the value for 02:00 to.
        assert values == list(range(24)) + [0, 1] + list(range(3, 24))
    report = response.json["report"]
    assert report["n_values"] == len(values)
    assert report["n_omitted"] == len(expected_report["omitted"])
    assert report["n_duplicated"] == len(expected_report["duplicated"])
    assert len(report["transitions"]) == 1
    transition = report["transitions"][0]
    for key, value in expected_report.items():
        assert transition[key] == value


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
def test_preview_requires_permission_to_post_data(
    client, soc_sensors, setup_supplier_account_reader, requesting_user, status_code
):
    response = preview(
        client,
        soc_sensors["hours"],
        start="2026-06-01T06:00+02:00",
        duration="PT1H",
        values=[80],
        unit="kWh",
        repeat="daily",
        until="2026-06-03",
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
        ("hours", dict(until="2026-06-01"), "repeat it until a later date"),
        ("hours", dict(duration="PT1H", values=[80, 90]), "or coarser"),
        ("hours", dict(unit="°C"), "Required unit"),
        ("hours", dict(repeat="weekly"), "Must be one of"),
        ("temperature", dict(unit="°C"), "instantaneous values"),
        # A daily sensor cannot keep fixed steps of 24 hours across the transition on October 25.
        (
            "days",
            dict(start="2026-10-19T00:00+02:00", duration="P1D", until="2026-10-27"),
            "cross a daylight saving time transition",
        ),
    ],
)
@pytest.mark.parametrize(
    "requesting_user", ["test_supplier_user_4@seita.nl"], indirect=True
)
def test_preview_refuses_invalid_patterns(
    client,
    setup_api_test_data,
    soc_sensors,
    requesting_user,
    sensor_key,
    changes,
    error_text,
):
    sensors = {
        **soc_sensors,
        "temperature": setup_api_test_data["some temperature sensor"],
    }
    pattern = dict(
        start="2026-06-01T06:00+02:00",
        duration="PT1H",
        values=[80],
        unit="kWh",
        repeat="daily",
        until="2026-06-03",
    )
    pattern.update(changes)

    response = preview(client, sensors[sensor_key], **pattern)

    assert response.status_code == 422
    assert error_text in str(response.json["message"])


@pytest.mark.parametrize(
    "requesting_user", ["test_supplier_user_4@seita.nl"], indirect=True
)
def test_preview_refuses_more_than_can_be_posted(
    client, soc_sensors, requesting_user, monkeypatch
):
    """Refuse repeats that would not fit in one request to post them."""
    monkeypatch.setitem(
        current_app.config, "FLEXMEASURES_MAX_SENSOR_DATA_INGESTION_BYTES", 2000
    )
    pattern = dict(
        start="2026-06-01T00:00+02:00",
        duration="P1D",
        values=24 * [80],
        unit="kWh",
        repeat="daily",
    )

    response = preview(client, soc_sensors["hours"], until="2026-06-03", **pattern)
    assert response.status_code == 200

    response = preview(client, soc_sensors["hours"], until="2026-06-30", **pattern)
    assert response.status_code == 422
    assert "more than can be posted in one request (2000 bytes)" in str(
        response.json["message"]
    )
