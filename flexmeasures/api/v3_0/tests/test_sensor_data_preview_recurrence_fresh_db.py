"""Test that a preview of repeated sensor values can be posted as it is, and is saved as previewed."""

from __future__ import annotations

from datetime import timedelta

from flask import url_for
import pandas as pd
import pytest
from sqlalchemy import select

from flexmeasures import Sensor
from flexmeasures.data.models.time_series import TimedBelief


@pytest.mark.parametrize("unit, factor", [("kWh", 1), ("MWh", 1000)])
@pytest.mark.parametrize(
    "requesting_user", ["test_supplier_user_4@seita.nl"], indirect=True
)
def test_post_previewed_recurrence(
    client, fresh_db, setup_api_fresh_test_data, requesting_user, unit, factor
):
    """Preview a pattern with a gap across the fall-back night, post the preview, and check the saved beliefs match it."""
    sensor = Sensor(
        name="soc minima",
        unit="kWh",
        event_resolution=timedelta(hours=1),
        timezone="Europe/Amsterdam",
        generic_asset=setup_api_fresh_test_data["some gas sensor"].generic_asset,
    )
    fresh_db.session.add(sensor)
    fresh_db.session.commit()

    preview = client.post(
        url_for("SensorAPI:preview_recurrence", id=sensor.id),
        json=dict(
            start="2026-10-23T00:00+02:00",
            duration="PT6H",
            values=[10, 11, 12, None, 14, 15],
            unit=unit,
            repeat="daily",
            until="2026-10-26",
        ),
    )
    assert preview.status_code == 200
    assert preview.json["report"]["n_duplicated"] == 1  # the 02:00 value on October 25

    response = client.post(
        url_for("SensorAPI:post_data", id=sensor.id), json=preview.json["data"]
    )
    assert response.status_code == 200

    data = preview.json["data"]
    previewed = pd.Series(
        data["values"],
        index=pd.date_range(
            pd.Timestamp(data["start"]), periods=len(data["values"]), freq="h"
        ),
        dtype=float,
    ).dropna()
    beliefs = fresh_db.session.scalars(
        select(TimedBelief).filter(TimedBelief.sensor_id == sensor.id)
    ).all()
    saved = pd.Series(
        {pd.Timestamp(b.event_start): b.event_value for b in beliefs}, dtype=float
    ).sort_index()
    assert len(saved) == preview.json["report"]["n_values"] == 3 * 5 + 1
    assert saved.index.equals(previewed.index.tz_convert("UTC"))
    assert (saved.values == previewed.values * factor).all()
