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
    create_annotation_account_relationship_table()
    create_annotation_asset_relationship_table()
    create_annotation_sensor_relationship_table()
    create_user_roles_unique_constraints()
    create_account_roles_unique_constraints()


def downgrade():
    click.confirm(
        "This downgrade drops the tables 'annotations_accounts', 'annotations_assets', 'annotations_sensors' and 'annotation'. Continue?",
        abort=True,
    )
    op.drop_constraint(
        op.f("roles_accounts_role_id_key"),
        "roles_accounts",
        type_="unique",
    )
    op.drop_constraint(
        op.f("roles_users_role_id_key"),
        "roles_users",
        type_="unique",
    )
    op.drop_constraint(
        op.f("annotations_accounts_annotation_id_key"),
        "annotations_accounts",
        type_="unique",
    )
    op.drop_constraint(
        op.f("annotations_assets_annotation_id_key"),
        "annotations_assets",
        type_="unique",
    )
    op.drop_constraint(
        op.f("annotations_sensors_annotation_id_key"),
        "annotations_sensors",
        type_="unique",
    )
    op.drop_table("annotations_accounts")
    op.drop_table("annotations_assets")
    op.drop_table("annotations_sensors")
    op.drop_constraint(op.f("annotation_content_key"), "annotation", type_="unique")
    op.drop_table("annotation")
    op.execute("DROP TYPE annotation_type;")


def create_account_roles_unique_constraints():
    """Remove any duplicate relationships, then constrain any new relationships to be unique."""
    op.execute(
        "DELETE FROM roles_accounts WHERE id in (SELECT r1.id FROM roles_accounts r1, roles_accounts r2 WHERE r1.id > r2.id AND r1.role_id = r2.role_id and r1.account_id = r2.account_id);"
    )
    op.create_unique_constraint(
        op.f("roles_accounts_role_id_key"),
        "roles_accounts",
        ["role_id", "account_id"],
    )


def create_user_roles_unique_constraints():
    """Remove any duplicate relationships, then constrain any new relationships to be unique."""
    op.execute(
        "DELETE FROM roles_users WHERE id in (SELECT r1.id FROM roles_users r1, roles_users r2 WHERE r1.id > r2.id AND r1.role_id = r2.role_id and r1.user_id = r2.user_id);"
    )
    op.create_unique_constraint(
        op.f("roles_users_role_id_key"),
        "roles_users",
        ["role_id", "user_id"],
    )


def create_annotation_sensor_relationship_table():
    op.create_table(
        "annotations_sensors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sensor_id", sa.Integer()),
        sa.Column("annotation_id", sa.Integer()),
        sa.ForeignKeyConstraint(("sensor_id",), ["sensor.id"]),
        sa.ForeignKeyConstraint(("annotation_id",), ["annotation.id"]),
    )
    op.create_unique_constraint(
        op.f("annotations_sensors_annotation_id_key"),
        "annotations_sensors",
        ["annotation_id", "sensor_id"],
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
    op.create_unique_constraint(
        op.f("annotations_assets_annotation_id_key"),
        "annotations_assets",
        ["annotation_id", "generic_asset_id"],
    )


def create_annotation_account_relationship_table():
    op.create_table(
        "annotations_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer()),
        sa.Column("annotation_id", sa.Integer()),
        sa.ForeignKeyConstraint(("account_id",), ["account.id"]),
        sa.ForeignKeyConstraint(("annotation_id",), ["annotation.id"]),
    )
    op.create_unique_constraint(
        op.f("annotations_accounts_annotation_id_key"),
        "annotations_accounts",
        ["annotation_id", "account_id"],
    )


def create_annotation_table():
    op.create_table(
        "annotation",
        sa.Column(
            "id", sa.Integer(), nullable=False, autoincrement=True, primary_key=True
        ),
        sa.Column("start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("belief_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column(
            "type",
            sa.Enum("alert", "holiday", "label", "feedback", name="annotation_type"),
            nullable=False,
        ),
        sa.Column("content", sa.String(1024), nullable=False),
        sa.ForeignKeyConstraint(("source_id",), ["data_source.id"]),
    )
    op.create_unique_constraint(
        op.f("annotation_content_key"),
        "annotation",
        ["content", "start", "belief_time", "source_id", "type"],
    )
