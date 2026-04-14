"""Tests for DELETE /api/v3_0/sensors/<id>/data with source, start and until filters.

These tests use fresh_db (function-scoped) to ensure data isolation between tests,
since each test mutates the sensor data.
"""

from __future__ import annotations

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
