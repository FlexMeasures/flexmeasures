"""create annotation table

Revision ID: 7f8b8920355f
Revises: c1d316c60985
Create Date: 2022-01-29 20:23:29.996133

"""
from alembic import op
import click
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "7f8b8920355f"
down_revision = "c1d316c60985"
branch_labels = None
depends_on = None


def upgrade():
    create_annotation_table()
    create_annotation_asset_relationship_table()
    create_annotation_sensor_relationship_table()


def downgrade():
    click.confirm(
        "This downgrade drops the tables 'annotations_assets', 'annotations_sensors' and 'annotation'. Continue?",
        abort=True,
    )
    op.drop_table("annotations_assets")
    op.drop_table("annotations_sensors")
    op.drop_constraint(op.f("annotation_name_key"), "annotation", type_="unique")
    op.drop_table("annotation")
    op.execute("DROP TYPE annotation_type;")


def create_annotation_sensor_relationship_table():
    op.create_table(
        "annotations_sensors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sensor_id", sa.Integer()),
        sa.Column("annotation_id", sa.Integer()),
        sa.ForeignKeyConstraint(("sensor_id",), ["sensor.id"]),
        sa.ForeignKeyConstraint(("annotation_id",), ["annotation.id"]),
    )


def create_annotation_asset_relationship_table():
    op.create_table(
        "annotations_assets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("generic_asset_id", sa.Integer()),
        sa.Column("annotation_id", sa.Integer()),
        sa.ForeignKeyConstraint(("generic_asset_id",), ["generic_asset.id"]),
        sa.ForeignKeyConstraint(("annotation_id",), ["annotation.id"]),
    )


def create_annotation_table():
    op.create_table(
        "annotation",
        sa.Column(
            "id", sa.Integer(), nullable=False, autoincrement=True, primary_key=True
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column(
            "type",
            sa.Enum("alert", "holiday", "label", name="annotation_type"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(("source_id",), ["data_source.id"]),
    )
    op.create_unique_constraint(
        op.f("annotation_name_key"),
        "annotation",
        ["name", "start", "source_id", "type"],
    )
