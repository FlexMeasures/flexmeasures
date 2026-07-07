"""Tests for DELETE /api/v3_0/sensors/<id>/data with source, start and until filters.

These tests use fresh_db (function-scoped) to ensure data isolation between tests,
since each test mutates the sensor data.
"""

from __future__ import annotations

import pandas as pd
import pytest

from flask import url_for
from sqlalchemy import select

from flexmeasures.data.models.time_series import TimedBelief
from flexmeasures import Sensor
from flexmeasures.api.v3_0.tests.utils import check_audit_log_event


@pytest.mark.parametrize("requesting_user", ["test_admin_user@seita.nl"], indirect=True)
def test_delete_sensor_data_by_source(
    client, setup_api_fresh_test_data, requesting_user, fresh_db
):
    """Deleting sensor data with a source filter only removes beliefs from that source."""
    existing_sensor = setup_api_fresh_test_data["some gas sensor"]
    existing_sensor_id = existing_sensor.id

    # Collect distinct source ids for this sensor
    all_beliefs = fresh_db.session.scalars(
        select(TimedBelief).filter(TimedBelief.sensor_id == existing_sensor_id)
    ).all()
    assert len(all_beliefs) > 0
    source_ids = list({b.source_id for b in all_beliefs})
    assert len(source_ids) >= 2, "Need at least two sources for this test"

    # Pick one source to delete
    source_id_to_delete = source_ids[0]

    # Delete sensor data for that source only
    delete_data_response = client.delete(
        url_for("SensorAPI:delete_data", id=existing_sensor_id),
        json={"source": source_id_to_delete},
    )
    assert delete_data_response.status_code == 204

    remaining_beliefs = fresh_db.session.scalars(
        select(TimedBelief).filter(TimedBelief.sensor_id == existing_sensor_id)
    ).all()

    # Beliefs from the deleted source should be gone
    deleted_source_beliefs = [
        b for b in remaining_beliefs if b.source_id == source_id_to_delete
    ]
    assert deleted_source_beliefs == []

    # Beliefs from other sources should remain
    other_beliefs = [b for b in remaining_beliefs if b.source_id != source_id_to_delete]
    assert len(other_beliefs) > 0

    deleted_sensor = fresh_db.session.get(Sensor, existing_sensor_id)
    assert deleted_sensor is not None, "Sensor itself should not be deleted"

    check_audit_log_event(
        db=fresh_db,
        event=f"Deleted data for sensor '{existing_sensor.name}': {existing_sensor.id}, source: {source_id_to_delete}",
        user=requesting_user,
        asset=existing_sensor.generic_asset,
    )


@pytest.mark.parametrize("requesting_user", ["test_admin_user@seita.nl"], indirect=True)
def test_delete_sensor_data_by_start(
    client, setup_api_fresh_test_data, requesting_user, fresh_db
):
    """Deleting sensor data with a start filter only removes beliefs at or after that time."""
    existing_sensor = setup_api_fresh_test_data["some gas sensor"]
    existing_sensor_id = existing_sensor.id

    all_beliefs = fresh_db.session.scalars(
        select(TimedBelief).filter(TimedBelief.sensor_id == existing_sensor_id)
    ).all()
    assert len(all_beliefs) >= 2

    # Use the second distinct event_start as the cutoff: beliefs at or after it should be deleted
    event_starts = sorted({b.event_start for b in all_beliefs})
    cutoff = event_starts[1]

    delete_data_response = client.delete(
        url_for("SensorAPI:delete_data", id=existing_sensor_id),
        json={"start": cutoff.isoformat()},
    )
    assert delete_data_response.status_code == 204

    remaining_beliefs = fresh_db.session.scalars(
        select(TimedBelief).filter(TimedBelief.sensor_id == existing_sensor_id)
    ).all()

    # All remaining beliefs should have event_start < cutoff
    for b in remaining_beliefs:
        assert b.event_start < cutoff

    deleted_sensor = fresh_db.session.get(Sensor, existing_sensor_id)
    assert deleted_sensor is not None, "Sensor itself should not be deleted"

    check_audit_log_event(
        db=fresh_db,
        event=f"Deleted data for sensor '{existing_sensor.name}': {existing_sensor.id}, from: {cutoff}",
        user=requesting_user,
        asset=existing_sensor.generic_asset,
    )


@pytest.mark.parametrize("requesting_user", ["test_admin_user@seita.nl"], indirect=True)
def test_delete_sensor_data_by_until(
    client, setup_api_fresh_test_data, requesting_user, fresh_db
):
    """Deleting sensor data with an until filter only removes beliefs before that time."""
    existing_sensor = setup_api_fresh_test_data["some gas sensor"]
    existing_sensor_id = existing_sensor.id

    all_beliefs = fresh_db.session.scalars(
        select(TimedBelief).filter(TimedBelief.sensor_id == existing_sensor_id)
    ).all()
    assert len(all_beliefs) >= 2

    # Use the last distinct event_start as the until cutoff:
    # beliefs strictly before it should be deleted
    event_starts = sorted({b.event_start for b in all_beliefs})
    cutoff = event_starts[-1]

    delete_data_response = client.delete(
        url_for("SensorAPI:delete_data", id=existing_sensor_id),
        json={"until": cutoff.isoformat()},
    )
    assert delete_data_response.status_code == 204

    remaining_beliefs = fresh_db.session.scalars(
        select(TimedBelief).filter(TimedBelief.sensor_id == existing_sensor_id)
    ).all()

    # All remaining beliefs should have event_start >= cutoff
    for b in remaining_beliefs:
        assert b.event_start >= cutoff

    deleted_sensor = fresh_db.session.get(Sensor, existing_sensor_id)
    assert deleted_sensor is not None, "Sensor itself should not be deleted"

    check_audit_log_event(
        db=fresh_db,
        event=f"Deleted data for sensor '{existing_sensor.name}': {existing_sensor.id}, until: {cutoff}",
        user=requesting_user,
        asset=existing_sensor.generic_asset,
    )


@pytest.mark.parametrize("requesting_user", ["test_admin_user@seita.nl"], indirect=True)
def test_delete_sensor_data_until_before_start_rejected(
    client, setup_api_fresh_test_data, requesting_user, fresh_db
):
    """Passing until < start must be rejected with 422."""
    existing_sensor = setup_api_fresh_test_data["some gas sensor"]

    response = client.delete(
        url_for("SensorAPI:delete_data", id=existing_sensor.id),
        json={
            "start": "2021-05-02T00:10:00+02:00",
            "until": "2021-05-02T00:00:00+02:00",  # before start
        },
    )
    assert response.status_code == 422


@pytest.mark.parametrize("requesting_user", ["test_admin_user@seita.nl"], indirect=True)
def test_delete_sensor_data_until_too_close_to_start_rejected(
    client, setup_api_fresh_test_data, requesting_user, fresh_db
):
    """For a non-instantaneous sensor (10-min resolution), until must be at least one
    resolution step after start.  Providing until == start must be rejected with 422."""
    existing_sensor = setup_api_fresh_test_data["some gas sensor"]
    # sensor has 10-minute resolution; start == until is less than one resolution step
    assert existing_sensor.event_resolution.total_seconds() == 600

    response = client.delete(
        url_for("SensorAPI:delete_data", id=existing_sensor.id),
        json={
            "start": "2021-05-02T00:00:00+02:00",
            "until": "2021-05-02T00:00:00+02:00",  # same as start — too close
        },
    )
    assert response.status_code == 422


@pytest.mark.parametrize("requesting_user", ["test_admin_user@seita.nl"], indirect=True)
def test_delete_sensor_data_instantaneous_sensor_same_datetime(
    client, setup_api_fresh_test_data, requesting_user, fresh_db
):
    """For an instantaneous sensor (zero resolution), start == until is valid and
    deletes the single data point recorded at that moment."""
    temperature_sensor = setup_api_fresh_test_data["some temperature sensor"]
    sensor_id = temperature_sensor.id
    assert temperature_sensor.event_resolution.total_seconds() == 0

    # Confirm a belief exists at the target moment
    target_dt = "2021-05-02T00:00:00+02:00"
    target_ts = pd.Timestamp(target_dt)
    all_beliefs_before = fresh_db.session.scalars(
        select(TimedBelief).filter(TimedBelief.sensor_id == sensor_id)
    ).all()
    assert any(b.event_start == target_ts for b in all_beliefs_before)

    response = client.delete(
        url_for("SensorAPI:delete_data", id=sensor_id),
        json={"start": target_dt, "until": target_dt},
    )
    assert response.status_code == 204

    remaining = fresh_db.session.scalars(
        select(TimedBelief).filter(TimedBelief.sensor_id == sensor_id)
    ).all()
    # The belief at the exact target moment must be gone
    assert not any(b.event_start == target_ts for b in remaining)
    # Other beliefs must be untouched
    assert len(remaining) == len(all_beliefs_before) - 1
