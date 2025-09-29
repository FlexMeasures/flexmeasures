"""Added flexmodel to generic asset model

Revision ID: f0ee99278f6f
Revises: cb8df44ebda5
Create Date: 2025-04-15 11:00:13.154048

"""

from __future__ import annotations

from typing import Iterable

from alembic import op
import sqlalchemy as sa

from flexmeasures.data.models.legacy_migration_utils import (
    upgrade_value,
    downgrade_value,
    NonDowngradableValueError,
)

# revision identifiers, used by Alembic.
revision = "f0ee99278f6f"
down_revision = "cb8df44ebda5"
branch_labels = None
depends_on = None

# All flex-model fields that, before upgrading, were supported as an asset attribute (float, quantity string, or sensor reference, or a list thereof):
FLEX_MODEL_FIELDS = {
    "min_soc_in_mwh": "soc-min",  # snake_case fallback attribute containing a float
    "max_soc_in_mwh": "soc-max",  # snake_case fallback attribute containing a float
    "soc-gain": "soc-gain",  # fallback attribute containing a list of quantity strings and/or sensor references
    "soc-usage": "soc-usage",  # fallback attribute containing a list of quantity strings and/or sensor references
    "roundtrip_efficiency": "roundtrip-efficiency",  # snake_case fallback attribute containing a float
    "charging-efficiency": "charging-efficiency",  # fallback attribute containing a quantity string, sensor reference or float
    "discharging-efficiency": "discharging-efficiency",  # fallback attribute containing a quantity string, sensor reference or float
    "storage_efficiency": "storage-efficiency",  # snake_case fallback attribute containing a quantity string, sensor reference or float
    "capacity_in_mw": "power-capacity",  # snake_case fallback attribute containing a quantity string or sensor reference
    "consumption_capacity": "consumption-capacity",  # snake_case fallback attribute containing a quantity string or sensor reference
    "production_capacity": "production-capacity",  # snake_case fallback attribute containing a quantity string or sensor reference
}
"""
The following flex-model fields exist that had no prior support as an asset attribute, and are therefore not migrated:
- soc-at-start
- soc-unit
- soc-minima
- soc-maxima
- soc-targets
- state-of-charge
- prefer-charging-sooner
- prefer-curtailing-later
"""


def upgrade():
    """Migrate db flex-model fields stored as asset/sensor attributes to a new flex_model db column."""

    # Add the new column
    with op.batch_alter_table("generic_asset", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("flex_model", sa.JSON(), nullable=False, server_default="{}")
        )

    sensor_table = sa.Table(
        "sensor",
        sa.MetaData(),
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("attributes", sa.JSON),
        sa.Column("generic_asset_id", sa.Integer),
    )

    asset_table, assets, conn = fetch_assets()

    def migrate_flex_model_fields(asset, sensors):
        """Migrate old flex-model fields (attributes) from the asset or its sensors to the asset's flex_model column.

         Steps:

         - Start with the asset's flex-model attribute (used as a backup in the downgrade step)
         - Pop all the relevant fields from the asset's attributes
         - For each of its sensors:
           - Pop all the relevant fields from the sensor's attributes
           - Check for ambiguous values
           - Save the sensor's new attributes (without the old fields)
        - Save the asset's new attributes (without the old fields) and the asset's new flex_model (with the new fields)
        """

        # Start by restoring the backup that might have been made in the downgrade of this migration
        asset_flex_model = asset.attributes.pop("flex-model", {})

        # Pop all the relevant fields from the asset's attributes
        for old_field_name, new_field_name in FLEX_MODEL_FIELDS.items():
            if (old_value := asset.attributes.pop(old_field_name, None)) is not None:
                asset_flex_model[new_field_name] = upgrade_value(
                    old_field_name, old_value, asset=asset
                )

        for sensor in sensors:

            # Pop all the relevant fields from the sensor's attributes
            for old_field_name, new_field_name in FLEX_MODEL_FIELDS.items():
                if (
                    old_value := sensor.attributes.pop(old_field_name, None)
                ) is not None:
                    new_value = upgrade_value(old_field_name, old_value, sensor=sensor)
                    if new_field_name not in asset.flex_model:
                        asset_flex_model[new_field_name] = new_value
                    elif new_value != asset_flex_model[new_field_name]:
                        # Check for ambiguous values
                        raise Exception(
                            f"Value mismatch for '{old_field_name}' in sensor {sensor.id}: sensor={new_value}, asset={asset.flex_model[new_field_name]}. "
                            f"Please file a GitHub Issue describing your situation."
                        )

            # Save the sensor's new attributes (without the old fields)
            stmt = (
                sensor_table.update()
                .where(sensor_table.c.id == sa.literal(sensor.id))
                .values(attributes=sensor.attributes)
            )
            conn.execute(stmt)

        # Save the asset's new attributes (without the old fields) and the asset's new flex_model (with the new fields)
        stmt = (
            asset_table.update()
            .where(asset_table.c.id == sa.literal(asset.id))
            .values(
                flex_model=asset_flex_model,
                attributes=asset.attributes,
            )
        )
        conn.execute(stmt)

    for asset in assets:
        # Fetch the sensors
        sensors = conn.execute(
            sa.select(
                sensor_table.c.id,
                sensor_table.c.attributes,
                sensor_table.c.generic_asset_id,
            ).where(sensor_table.c.generic_asset_id == sa.literal(asset.id))
        ).fetchall()

        # Migrate the asset's flex-model fields
        migrate_flex_model_fields(asset=asset, sensors=sensors)


def downgrade():
    """Migrate the flex_model db column to an asset attribute.

    Also restore fallback asset attributes used by code before this migration.
    """
    asset_table, assets, conn = fetch_assets()

    # Process each generic asset
    for asset in assets:
        asset_id = asset.id
        flex_model_data = asset.flex_model

        # Revert flex-model data to attributes
        if flex_model_data is not None:

            # Ensure that the flex-model attribute is available for backing up the flex-model data
            asset_attrs_flex_model = asset.attributes.get("flex-model", {})
            if asset_attrs_flex_model:
                raise NotImplementedError(
                    f"Asset {asset_id} already has a 'flex-model' attribute, so it is unavailable for backing up the flex-model data"
                )
            asset_attrs = asset.attributes or {}

            for old_field_name, new_field_name in FLEX_MODEL_FIELDS.items():
                if new_field_name not in flex_model_data:
                    continue
                new_value = flex_model_data[new_field_name]
                try:
                    asset_attrs[old_field_name] = downgrade_value(
                        old_field_name, new_value
                    )

                    # Remove the new field from the flex-model data
                    flex_model_data.pop(new_field_name)
                except NonDowngradableValueError:
                    continue

            # Back up the remaining flex-model data as the flex-model attribute (if not empty)
            if flex_model_data:
                asset_attrs["flex-model"] = flex_model_data

            # Update the generic asset attributes
            stmt = (
                asset_table.update()
                .where(asset_table.c.id == sa.literal(asset_id))
                .values(attributes=asset_attrs)
            )
            conn.execute(stmt)

    with op.batch_alter_table("generic_asset", schema=None) as batch_op:
        batch_op.drop_column("flex_model")


def fetch_assets() -> tuple[sa.Table, Iterable[sa.Row], sa.Connection]:
    """Fetch the part of the asset table needed for this migration."""
    asset_table = sa.Table(
        "generic_asset",
        sa.MetaData(),
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("flex_model", sa.JSON),
        sa.Column("attributes", sa.JSON),
    )

    # Fetch all assets
    conn = op.get_bind()
    result = conn.execute(
        sa.select(
            asset_table.c.id,
            asset_table.c.flex_model,
            asset_table.c.attributes,
        )
    )
    assets = result.fetchall()
    return asset_table, assets, conn
