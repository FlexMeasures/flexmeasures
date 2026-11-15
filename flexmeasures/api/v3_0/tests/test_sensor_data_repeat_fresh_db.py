"""Test that posting values to repeat saves exactly what a dry run of the same request says it would save."""

from __future__ import annotations

from datetime import timedelta

from flask import url_for
import pandas as pd
import pytest
from sqlalchemy import select

from flexmeasures import Sensor
from flexmeasures.data.models.time_series import TimedBelief


@pytest.mark.parametrize(
    "tz, body, factor",
    [
        # A pattern with a gap across the fall-back night, in the sensor's unit and in another one.
        (
            "Europe/Amsterdam",
            dict(
                start="2026-10-23T00:00+02:00",
                duration="PT6H",
                values=[10, 11, 12, None, 14, 15],
                unit="kWh",
                repeat="daily",
                until="2026-10-26",
            ),
            1,
        ),
        (
            "Europe/Amsterdam",
            dict(
                start="2026-10-23T00:00+02:00",
                duration="PT6H",
                values=[10, 11, 12, None, 14, 15],
                unit="MWh",
                repeat="daily",
                until="2026-10-26",
            ),
            1000,
        ),
        # A Saturday pattern on workdays: the pattern itself is not saved.
        (
            "Europe/Amsterdam",
            dict(
                start="2026-10-24T06:00+02:00",
                duration="PT2H",
                values=[80, 90],
                unit="kWh",
                repeat="workdays",
                until="2026-10-28",
            ),
            1,
        ),
        # Hourly values on Lord Howe Island, with an extra event overlapping its neighbour in the fall-back night.
        (
            "Australia/Lord_Howe",
            dict(
                start="2026-04-04T00:00+11:00",
                duration="P1D",
                values=list(range(24)),
                unit="kWh",
                repeat="daily",
                until="2026-04-05",
            ),
            1,
        ),
    ],
)
@pytest.mark.parametrize(
    "requesting_user", ["test_supplier_user_4@seita.nl"], indirect=True
)
def test_post_repeated_values_as_dry_run_says(
    client, fresh_db, setup_api_fresh_test_data, requesting_user, tz, body, factor
):
    sensor = Sensor(
        name="soc minima",
        unit="kWh",
        event_resolution=timedelta(hours=1),
        timezone=tz,
        generic_asset=setup_api_fresh_test_data["some gas sensor"].generic_asset,
    )
    fresh_db.session.add(sensor)
    fresh_db.session.commit()
    url = url_for("SensorAPI:post_data", id=sensor.id)

    dry_run = client.post(url, json={**body, "dry-run": True})
    assert dry_run.status_code == 200
    response = client.post(url, json=body)
    assert response.status_code == 200
    # The report comes with the saved values too, and says the same.
    assert response.json["report"] == dry_run.json["report"]

    previewed = pd.concat(
        [
            pd.Series(
                chunk["values"],
                index=pd.date_range(
                    pd.Timestamp(chunk["start"]),
                    periods=len(chunk["values"]),
                    freq="h",
                ),
                dtype=float,
            )
            for chunk in dry_run.json["data"]
        ]
    ).dropna()
    beliefs = fresh_db.session.scalars(
        select(TimedBelief).filter(TimedBelief.sensor_id == sensor.id)
    ).all()
    saved = pd.Series(
        {pd.Timestamp(b.event_start): b.event_value for b in beliefs}, dtype=float
    ).sort_index()
    assert len(saved) == dry_run.json["report"]["n-values"]
    assert saved.index.equals(previewed.index.tz_convert("UTC").sort_values())
    # Unit conversion may round the last digit, depending on the conversions pint has cached before.
    assert list(saved.values) == pytest.approx(
        list(previewed.sort_index().values * factor)
    )
