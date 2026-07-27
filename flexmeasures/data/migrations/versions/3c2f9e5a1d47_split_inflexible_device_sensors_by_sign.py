"""Split inflexible-device-sensors into inflexible-consumption and inflexible-production

Data-only migration: in each stored flex-context (the ``generic_asset.flex_context``
column, including any nested ``commodities`` entries), the deprecated
``inflexible-device-sensors`` list of bare sensor ids is split into the sign-explicit
``inflexible-consumption`` and ``inflexible-production`` lists of sensor references.

Each sensor is classified by its ``consumption_is_positive`` attribute (falling back
to its asset's attribute, defaulting to False), mirroring how the deprecated field's
data was read (``Sensor.get_attribute`` in ``get_power_values``), so the migration is
behavior-preserving. The attribute itself is kept on the sensor: trigger messages
cannot be migrated, so the deprecated field remains supported and keeps reading it.

The downgrade merges the sensor references back into a bare-id list. Source filters
possibly added to the references after upgrading are dropped (lossy), and sensors
listed under ``inflexible-consumption`` without an explicit ``consumption_is_positive``
attribute get the attribute set to True, preserving how their data is read.

Revision ID: 3c2f9e5a1d47
Revises: 4b0f2e9c1a6d
Create Date: 2026-07-27 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "3c2f9e5a1d47"
down_revision = "4b0f2e9c1a6d"
branch_labels = None
depends_on = None


generic_asset_table = sa.Table(
    "generic_asset",
    sa.MetaData(),
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("attributes", sa.JSON),
    sa.Column("flex_context", sa.JSON),
)

sensor_table = sa.Table(
    "sensor",
    sa.MetaData(),
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("attributes", sa.JSON),
    sa.Column("generic_asset_id", sa.Integer),
)


def _classify_consumption_is_positive(conn, sensor_id: int) -> bool:
    """Mirror the legacy read path's Sensor.get_attribute lookup:
    the sensor's own attribute, else its asset's attribute, else False.

    Dangling sensor ids classify as False (production-positive, the old default).
    """
    row = conn.execute(
        sa.select(sensor_table.c.attributes, sensor_table.c.generic_asset_id).where(
            sensor_table.c.id == sensor_id
        )
    ).first()
    if row is None:
        return False
    attributes = row.attributes or {}
    if "consumption_is_positive" in attributes:
        return bool(attributes["consumption_is_positive"])
    asset_attributes = (
        conn.execute(
            sa.select(generic_asset_table.c.attributes).where(
                generic_asset_table.c.id == row.generic_asset_id
            )
        ).scalar()
        or {}
    )
    return bool(asset_attributes.get("consumption_is_positive", False))


def _split_context(conn, context: dict) -> bool:
    """Split one (commodity) context's inflexible-device-sensors in place."""
    if "inflexible-device-sensors" not in context:
        return False
    sensor_ids = context.pop("inflexible-device-sensors") or []
    for sensor_id in sensor_ids:
        key = (
            "inflexible-consumption"
            if _classify_consumption_is_positive(conn, sensor_id)
            else "inflexible-production"
        )
        context.setdefault(key, []).append({"sensor": sensor_id})
    if not sensor_ids:
        # An explicitly-empty list shadows any ancestor asset's inflexible devices;
        # keep that by defining an (equally empty) member of the same field family.
        context.setdefault("inflexible-production", [])
    return True


def _merge_context(conn, context: dict) -> bool:
    """Merge one (commodity) context's sign-explicit lists back in place (lossy: source filters are dropped)."""
    changed = False
    sensor_ids = []
    for key, consumption_is_positive in (
        ("inflexible-consumption", True),
        ("inflexible-production", False),
    ):
        if key not in context:
            continue
        changed = True
        for entry in context.pop(key) or []:
            sensor_id = entry["sensor"] if isinstance(entry, dict) else entry
            sensor_ids.append(sensor_id)
            if consumption_is_positive:
                # Preserve how this sensor's data is read by the merged-back field
                _ensure_sensor_attribute_true(conn, sensor_id)
    if changed:
        context["inflexible-device-sensors"] = sensor_ids
    return changed


def _ensure_sensor_attribute_true(conn, sensor_id: int) -> None:
    row = conn.execute(
        sa.select(sensor_table.c.attributes).where(sensor_table.c.id == sensor_id)
    ).first()
    if row is None:
        return
    attributes = row.attributes or {}
    if attributes.get("consumption_is_positive") is True:
        return
    attributes["consumption_is_positive"] = True
    conn.execute(
        sensor_table.update()
        .where(sensor_table.c.id == sensor_id)
        .values(attributes=attributes)
    )


def _rewrite_flex_contexts(transform) -> None:
    conn = op.get_bind()
    for asset_id, flex_context in conn.execute(
        sa.select(generic_asset_table.c.id, generic_asset_table.c.flex_context)
    ).fetchall():
        if not flex_context:
            continue
        changed = transform(conn, flex_context)
        for commodity_context in flex_context.get("commodities") or []:
            changed |= transform(conn, commodity_context)
        if changed:
            conn.execute(
                generic_asset_table.update()
                .where(generic_asset_table.c.id == asset_id)
                .values(flex_context=flex_context)
            )


def upgrade():
    _rewrite_flex_contexts(_split_context)


def downgrade():
    _rewrite_flex_contexts(_merge_context)
