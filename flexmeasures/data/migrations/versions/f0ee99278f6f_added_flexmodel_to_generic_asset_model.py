"""Added flexmodel to generic asset model

Revision ID: f0ee99278f6f
Revises: cb8df44ebda5
Create Date: 2025-04-15 11:00:13.154048

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from collections import defaultdict

from flexmeasures.utils.unit_utils import is_power_unit, is_energy_unit, ur

# revision identifiers, used by Alembic.
revision = "f0ee99278f6f"
down_revision = "cb8df44ebda5"
branch_labels = None
depends_on = None

# all flex-model fields that, before upgrading, were supported as a sensor or asset attribute
FLEX_MODEL_FIELDS = dict(
    min_soc_in_mwh="soc-min",
)


def group_sensors_by_field(sensors, conn, generic_asset_table) -> list[dict]:
    """
    This function groups sensors by flexmodel fields (using the old field names) and checks for value mismatches.
    """
    field_specs = []

    # construct the field specifications
    for old_field_name, new_field_name in FLEX_MODEL_FIELDS.items():
        field_spec = dict(
            new_field_name=new_field_name,
            old_field_name=old_field_name,
            grouped=defaultdict(list),
        )
        field_specs.append(field_spec)

    # iterate over the sensors and group them by field
    # and check for value mismatches
    for sensor in sensors:
        # fetch the generic asset
        sensor_generic_asset = conn.execute(
            sa.select(
                generic_asset_table.c.id,
                generic_asset_table.c.attributes,
            ).where(generic_asset_table.c.id == sensor.generic_asset_id)
        ).fetchone()

        if sensor_generic_asset is None:
            raise Exception(
                f"Generic asset not found for sensor {sensor.id} with asset_id {sensor.generic_asset_id}"
            )

        sensor_attrs = sensor.attributes or {}
        asset_attrs = sensor_generic_asset.attributes or {}

        for field_spec in field_specs:
            old_field_name = field_spec["old_field_name"]

            # check if old_field_name exist on both attributes on sensor and asset
            sensor_val = sensor_attrs.get(old_field_name)
            asset_val = asset_attrs.get(old_field_name)

            if sensor_val is not None and asset_val is not None:
                if sensor_val != asset_val:
                    raise Exception(
                        f"Value mismatch for '{old_field_name}' in sensor {sensor.id}: sensor={sensor_val}, asset={asset_val}. "
                        f"Please file a GitHub Issue describing your situation."
                    )

            # check if old_field_name exist on sensor attributes
            if sensor_val is not None:
                field_spec["grouped"][sensor_generic_asset].append(sensor)

    return field_specs


def validate_for_duplicate_keys(fields_specs):
    """
    This function checks for duplicate keys in the grouped sensors of a parent asset.
    """
    for field_spec in fields_specs:
        grouped = field_spec["grouped"]
        for asset, sensors in grouped.items():
            if len(sensors) > 1 and any(
                [
                    sensor.get_attribute(field_spec["old_field_name"])
                    != sensors[0].get_attribute(field_spec["old_field_name"])
                    for sensor in sensors
                ]
            ):
                raise Exception(
                    f"Multiple sensors found with different '{field_spec['old_field_name']}' values for asset_id {asset.id}: {[s.id for s in sensors]}. "
                    f"Please file a GitHub Issue describing your situation."
                )


def upgrade():
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

    generic_asset_table = sa.Table(
        "generic_asset",
        sa.MetaData(),
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("flex_model", sa.JSON),
        sa.Column("attributes", sa.JSON),
    )

    # Fetch all sensors
    conn = op.get_bind()
    result = conn.execute(
        sa.select(
            sensor_table.c.id,
            sensor_table.c.attributes,
            sensor_table.c.generic_asset_id,
        )
    )
    sensors = result.fetchall()

    fields_specs = group_sensors_by_field(sensors, conn, generic_asset_table)

    # Check for duplicate keys in the grouped sensors
    validate_for_duplicate_keys(fields_specs)

    # Process each group
    for field_spec in fields_specs:
        old_name = field_spec["old_field_name"]
        new_name = field_spec["new_field_name"]

        # Check if the key exist on any asset's attributes and move that into the asset's flex_model
        # This is to ensure that the flex_model is not empty in the edge case where the asset has no
        # sensors or has no sensors using the field/key
        asset_result = conn.execute(
            sa.select(
                generic_asset_table.c.id,
                generic_asset_table.c.attributes,
                generic_asset_table.c.flex_model,
            ).where(
                sa.func.jsonb_path_exists(
                    sa.cast(generic_asset_table.c.attributes, JSONB),
                    f'$."flex-model"."{new_name}"',
                )
                | sa.cast(generic_asset_table.c.attributes, JSONB).has_key(old_name)
            )
        )

        affected_assets = asset_result.fetchall()

        for asset in affected_assets:
            asset_id = asset.id
            asset_attr = asset.attributes or {}
            asset_attr_flex_model = asset_attr.get("flex-model", {})
            flex_model_data = {**asset_attr_flex_model, **asset_attr}

            # check if value is a int, bool, float or dict
            if not isinstance(flex_model_data[old_name], (int, float, dict, bool)):
                raise Exception(
                    f"Invalid value for '{old_name}' in generic asset {asset_id}: {flex_model_data[old_name]}"
                )

            if old_name[-6:] == "in_mwh":
                # convert from float (in MWh) to string (in kWh)
                value_in_kwh = flex_model_data[old_name] * 1000
                flex_model_data[new_name] = f"{value_in_kwh} kWh"
            elif old_name[-6:] == "in_mw":
                # convert from float (in MW) to string (in kW)
                value_in_kw = flex_model_data[old_name] * 1000
                flex_model_data[new_name] = f"{value_in_kw} kW"
            else:
                # move as is
                value = flex_model_data[old_name]
                flex_model_data[new_name] = value

            # Update the generic asset attributes to remove 'old_name' and add 'new_name' to flex_model
            asset_attr_flex_model.pop(new_name, None)
            asset_attr.pop(old_name, None)
            flex_model_data.pop(old_name)
            flex_model_data.pop("flex-model", None)
            stmt = (
                generic_asset_table.update()
                .where(generic_asset_table.c.id == asset_id)
                .values(
                    flex_model=flex_model_data,
                    attributes=asset_attr,
                )
            )
            conn.execute(stmt)

        # Process the grouped sensors
        for sensor_generic_asset, sensors_with_key in field_spec["grouped"].items():
            for sensor in sensors_with_key:
                field_value = None

                if sensor.attributes.get(old_name) is not None:
                    field_value = sensor.attributes.get(old_name)
                elif sensor_generic_asset.attributes.get(old_name) is not None:
                    field_value = sensor_generic_asset.attributes.get(old_name)

                if field_value is not None:
                    # check if value is a int or float
                    if not isinstance(field_value, (int, float)):
                        raise Exception(
                            f"Invalid value for '{old_name}' in sensor {sensor.id}: {sensor.attributes[old_name]}"
                        )

                    soc_min_value_kwh = field_value * 1000
                    soc_min_in_kwh = f"{soc_min_value_kwh} kWh"
                    flex_model_data = {new_name: soc_min_in_kwh}

                    # Update the generic asset attributes to remove 'old_name' and add 'new_name' to flex_model
                    sensor_generic_asset.attributes.pop(old_name, None)
                    stmt = (
                        generic_asset_table.update()
                        .where(generic_asset_table.c.id == asset_id)
                        .values(
                            flex_model=flex_model_data,
                            attributes=sensor_generic_asset.attributes,
                        )
                    )

                    conn.execute(stmt)

                    # Update the sensor attributes to remove 'old_name' and add 'new_name'
                    sensor.attributes.pop(old_name, None)
                    stmt = (
                        sensor_table.update()
                        .where(sensor_table.c.id == sensor.id)
                        .values(attributes=sensor.attributes)
                    )
                    conn.execute(stmt)


def downgrade():
    with op.batch_alter_table("generic_asset", schema=None) as batch_op:
        generic_asset_table = sa.Table(
            "generic_asset",
            sa.MetaData(),
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("flex_model", sa.JSON),
            sa.Column("attributes", sa.JSON),
        )

        # Fetch all generic assets
        conn = op.get_bind()
        result = conn.execute(
            sa.select(
                generic_asset_table.c.id,
                generic_asset_table.c.flex_model,
                generic_asset_table.c.attributes,
            )
        )
        generic_assets = result.fetchall()

        # Process each generic asset
        for asset in generic_assets:
            asset_id = asset.id
            flex_model_data = asset.flex_model

            # Revert flex-model data to attributes
            if flex_model_data is not None:

                asset_attrs_flex_model = asset.attributes.get("flex-model", {})
                asset_attrs = asset.attributes or {}

                for old_field_name, new_field_name in FLEX_MODEL_FIELDS.items():
                    if new_field_name in flex_model_data and isinstance(
                        flex_model_data[new_field_name], str
                    ):
                        # Convert the value back to the original format
                        value = flex_model_data[new_field_name]
                        if old_field_name[-6:] == "in_mwh" and is_energy_unit(value):
                            value_in_mwh = ur.Quantity(value).to("MWh").magnitude
                            asset_attrs[old_field_name] = value_in_mwh
                        elif old_field_name[-6:] == "in_mw" and is_power_unit(value):
                            value_in_mw = ur.Quantity(value).to("MW").magnitude
                            asset_attrs[old_field_name] = value_in_mw
                        else:
                            asset_attrs[old_field_name] = value
                    elif new_field_name in flex_model_data and isinstance(
                        flex_model_data[new_field_name], dict
                    ):
                        asset_attrs_flex_model[new_field_name] = value

                # Remove the new fields from the attributes flex-model data
                asset_attrs_flex_model.pop(new_field_name, None)
                # update flex-model data in attributes
                asset_attrs["flex-model"] = asset_attrs_flex_model

                # Update the generic asset attributes
                stmt = (
                    generic_asset_table.update()
                    .where(generic_asset_table.c.id == asset_id)
                    .values(attributes=asset_attrs)
                )
                conn.execute(stmt)

        batch_op.drop_column("flex_model")

    # ### end Alembic commands ###
