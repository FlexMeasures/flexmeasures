"""Add ondelete cascade to foreign keys in GenericAssetAnnotationRelationship

Revision ID: 9b2b90ee5dbf
Revises: 524800c11eec
Create Date: 2024-08-22 12:22:45.240872

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "9b2b90ee5dbf"
down_revision = "524800c11eec"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("annotations_assets", schema=None) as batch_op:
        batch_op.drop_constraint(
            "annotations_assets_generic_asset_id_generic_asset_fkey", type_="foreignkey"
        )
        batch_op.drop_constraint(
            "annotations_assets_annotation_id_annotation_fkey", type_="foreignkey"
        )
        batch_op.create_foreign_key(
            batch_op.f("annotations_assets_generic_asset_id_generic_asset_fkey"),
            "generic_asset",
            ["generic_asset_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            batch_op.f("annotations_assets_annotation_id_annotation_fkey"),
            "annotation",
            ["annotation_id"],
            ["id"],
            ondelete="CASCADE",
        )
    with op.batch_alter_table("annotations_accounts", schema=None) as batch_op:
        batch_op.drop_constraint(
            "annotations_accounts_account_id_account_fkey", type_="foreignkey"
        )
        batch_op.drop_constraint(
            "annotations_accounts_annotation_id_annotation_fkey", type_="foreignkey"
        )
        batch_op.create_foreign_key(
            batch_op.f("annotations_accounts_account_id_account_fkey"),
            "account",
            ["account_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            batch_op.f("annotations_accounts_annotation_id_annotation_fkey"),
            "annotation",
            ["annotation_id"],
            ["id"],
            ondelete="CASCADE",
        )

    with op.batch_alter_table("annotations_sensors", schema=None) as batch_op:
        batch_op.drop_constraint(
            "annotations_sensors_annotation_id_annotation_fkey", type_="foreignkey"
        )
        batch_op.drop_constraint(
            "annotations_sensors_sensor_id_sensor_fkey", type_="foreignkey"
        )
        batch_op.create_foreign_key(
            batch_op.f("annotations_sensors_annotation_id_annotation_fkey"),
            "annotation",
            ["annotation_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            batch_op.f("annotations_sensors_sensor_id_sensor_fkey"),
            "sensor",
            ["sensor_id"],
            ["id"],
            ondelete="CASCADE",
        )


def downgrade():
    with op.batch_alter_table("annotations_assets", schema=None) as batch_op:
        batch_op.drop_constraint(
            batch_op.f("annotations_assets_annotation_id_annotation_fkey"),
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            batch_op.f("annotations_assets_generic_asset_id_generic_asset_fkey"),
            type_="foreignkey",
        )
        batch_op.create_foreign_key(
            "annotations_assets_annotation_id_annotation_fkey",
            "annotation",
            ["annotation_id"],
            ["id"],
        )
        batch_op.create_foreign_key(
            "annotations_assets_generic_asset_id_generic_asset_fkey",
            "generic_asset",
            ["generic_asset_id"],
            ["id"],
        )

    with op.batch_alter_table("annotations_sensors", schema=None) as batch_op:
        batch_op.drop_constraint(
            batch_op.f("annotations_sensors_sensor_id_sensor_fkey"), type_="foreignkey"
        )
        batch_op.drop_constraint(
            batch_op.f("annotations_sensors_annotation_id_annotation_fkey"),
            type_="foreignkey",
        )
        batch_op.create_foreign_key(
            "annotations_sensors_sensor_id_sensor_fkey", "sensor", ["sensor_id"], ["id"]
        )
        batch_op.create_foreign_key(
            "annotations_sensors_annotation_id_annotation_fkey",
            "annotation",
            ["annotation_id"],
            ["id"],
        )

    with op.batch_alter_table("annotations_accounts", schema=None) as batch_op:
        batch_op.drop_constraint(
            batch_op.f("annotations_accounts_annotation_id_annotation_fkey"),
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            batch_op.f("annotations_accounts_account_id_account_fkey"),
            type_="foreignkey",
        )
        batch_op.create_foreign_key(
            "annotations_accounts_annotation_id_annotation_fkey",
            "annotation",
            ["annotation_id"],
            ["id"],
        )
        batch_op.create_foreign_key(
            "annotations_accounts_account_id_account_fkey",
            "account",
            ["account_id"],
            ["id"],
        )
