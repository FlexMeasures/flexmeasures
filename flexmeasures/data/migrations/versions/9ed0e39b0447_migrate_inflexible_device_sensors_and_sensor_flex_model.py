"""Migrate inflexible-device-sensors to inflexible-loads/generators, and sensor to consumption/production in flex-model

Revision ID: 9ed0e39b0447
Revises: f0ee99278f6f
Create Date: 2025-05-30 00:00:00.000000

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = "9ed0e39b0447"
down_revision = "f0ee99278f6f"
branch_labels = None
depends_on = None


def _get_consumption_is_positive(connection, sensor_id: int) -> bool:
    """Look up a sensor's consumption_is_positive attribute (defaults to False)."""
    row = connection.execute(
        sa.text("SELECT attributes FROM sensor WHERE id = :sensor_id"),
        {"sensor_id": sensor_id},
    ).fetchone()
    if row is not None:
        attributes = row[0] or {}
        return attributes.get("consumption_is_positive", False)
    # Sensor not found: default to production-positive (FlexMeasures default)
    return False


def _migrate_flex_context(connection, asset_id: int, flex_context: dict) -> None:
    """Convert inflexible-device-sensors → inflexible-loads / inflexible-generators."""
    old_sensor_ids = flex_context.get("inflexible-device-sensors", [])
    if not old_sensor_ids:
        return

    loads = list(flex_context.get("inflexible-loads", []))
    generators = list(flex_context.get("inflexible-generators", []))

    for sensor_id in old_sensor_ids:
        if _get_consumption_is_positive(connection, sensor_id):
            loads.append(sensor_id)
        else:
            generators.append(sensor_id)

    new_flex_context = dict(flex_context)
    del new_flex_context["inflexible-device-sensors"]
    if loads:
        new_flex_context["inflexible-loads"] = loads
    if generators:
        new_flex_context["inflexible-generators"] = generators

    connection.execute(
        sa.text(
            "UPDATE generic_asset SET flex_context = :flex_context WHERE id = :asset_id"
        ),
        {"flex_context": sa.cast(new_flex_context, JSONB), "asset_id": asset_id},
    )


def _migrate_flex_model(connection, asset_id: int, flex_model: list) -> None:
    """Convert sensor key → consumption or production in flex-model entries."""
    changed = False
    new_flex_model = []
    for entry in flex_model:
        if not isinstance(entry, dict) or "sensor" not in entry:
            new_flex_model.append(entry)
            continue
        sensor_id = entry["sensor"]
        new_entry = dict(entry)
        del new_entry["sensor"]
        if _get_consumption_is_positive(connection, sensor_id):
            new_entry["consumption"] = sensor_id
        else:
            new_entry["production"] = sensor_id
        new_flex_model.append(new_entry)
        changed = True

    if changed:
        connection.execute(
            sa.text(
                "UPDATE generic_asset SET flex_model = :flex_model WHERE id = :asset_id"
            ),
            {"flex_model": sa.cast(new_flex_model, JSONB), "asset_id": asset_id},
        )


def upgrade():
    """
    Migrate flex-context and flex-model on generic_asset:

    1. flex-context: Convert `inflexible-device-sensors` list to `inflexible-loads` and
       `inflexible-generators` based on each sensor's `consumption_is_positive` attribute.

    2. flex-model: Convert entries with `sensor` key to either `consumption` or `production`
       based on the sensor's `consumption_is_positive` attribute.
    """
    connection = op.get_bind()

    for asset_id, flex_context in connection.execute(
        sa.text(
            "SELECT id, flex_context FROM generic_asset "
            "WHERE flex_context ? 'inflexible-device-sensors'"
        )
    ).fetchall():
        if flex_context:
            _migrate_flex_context(connection, asset_id, flex_context)

    for asset_id, flex_model in connection.execute(
        sa.text(
            "SELECT id, flex_model FROM generic_asset "
            "WHERE flex_model IS NOT NULL AND jsonb_typeof(flex_model) = 'array'"
        )
    ).fetchall():
        if flex_model:
            _migrate_flex_model(connection, asset_id, flex_model)


def _downgrade_flex_context(connection, asset_id: int, flex_context: dict) -> None:
    """Combine inflexible-loads + inflexible-generators back to inflexible-device-sensors."""
    sensor_ids = list(flex_context.get("inflexible-loads", [])) + list(
        flex_context.get("inflexible-generators", [])
    )
    new_flex_context = dict(flex_context)
    new_flex_context.pop("inflexible-loads", None)
    new_flex_context.pop("inflexible-generators", None)
    if sensor_ids:
        new_flex_context["inflexible-device-sensors"] = sensor_ids
    connection.execute(
        sa.text(
            "UPDATE generic_asset SET flex_context = :flex_context WHERE id = :asset_id"
        ),
        {"flex_context": sa.cast(new_flex_context, JSONB), "asset_id": asset_id},
    )


def _downgrade_flex_model(connection, asset_id: int, flex_model: list) -> None:
    """Convert consumption/production back to sensor in flex-model entries."""
    changed = False
    new_flex_model = []
    for entry in flex_model:
        if not isinstance(entry, dict):
            new_flex_model.append(entry)
            continue
        new_entry = dict(entry)
        if "consumption" in new_entry:
            new_entry["sensor"] = new_entry.pop("consumption")
            changed = True
        elif "production" in new_entry:
            new_entry["sensor"] = new_entry.pop("production")
            changed = True
        new_flex_model.append(new_entry)
    if changed:
        connection.execute(
            sa.text(
                "UPDATE generic_asset SET flex_model = :flex_model WHERE id = :asset_id"
            ),
            {"flex_model": sa.cast(new_flex_model, JSONB), "asset_id": asset_id},
        )


def downgrade():
    """
    Reverse migration: convert inflexible-loads/generators back to inflexible-device-sensors,
    and consumption/production back to sensor in flex-model.
    """
    connection = op.get_bind()

    for asset_id, flex_context in connection.execute(
        sa.text(
            "SELECT id, flex_context FROM generic_asset "
            "WHERE flex_context ? 'inflexible-loads' OR flex_context ? 'inflexible-generators'"
        )
    ).fetchall():
        if flex_context:
            _downgrade_flex_context(connection, asset_id, flex_context)

    for asset_id, flex_model in connection.execute(
        sa.text(
            "SELECT id, flex_model FROM generic_asset "
            "WHERE flex_model IS NOT NULL AND jsonb_typeof(flex_model) = 'array'"
        )
    ).fetchall():
        if flex_model:
            _downgrade_flex_model(connection, asset_id, flex_model)
