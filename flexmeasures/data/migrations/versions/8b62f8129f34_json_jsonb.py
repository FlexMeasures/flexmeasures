"""JSON -> JSONB

Revision ID: 8b62f8129f34
Revises: 6cca6c002135
Create Date: 2025-12-13 02:12:01.765772

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "8b62f8129f34"
down_revision = "6cca6c002135"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("data_source", schema=None) as batch_op:
        batch_op.alter_column(
            "attributes",
            existing_type=postgresql.JSON(astext_type=sa.Text()),
            type_=postgresql.JSONB(astext_type=sa.Text()),
            existing_nullable=False,
            existing_server_default=sa.text("'{}'::json"),
        )

    with op.batch_alter_table("generic_asset", schema=None) as batch_op:
        batch_op.alter_column(
            "attributes",
            existing_type=postgresql.JSON(astext_type=sa.Text()),
            type_=postgresql.JSONB(astext_type=sa.Text()),
            existing_nullable=False,
        )
        batch_op.alter_column(
            "sensors_to_show",
            existing_type=postgresql.JSON(astext_type=sa.Text()),
            type_=postgresql.JSONB(astext_type=sa.Text()),
            existing_nullable=False,
            existing_server_default=sa.text("'[]'::json"),
        )
        batch_op.alter_column(
            "flex_context",
            existing_type=postgresql.JSON(astext_type=sa.Text()),
            type_=postgresql.JSONB(astext_type=sa.Text()),
            existing_nullable=False,
            existing_server_default=sa.text("'{}'::json"),
        )
        batch_op.alter_column(
            "flex_model",
            existing_type=postgresql.JSON(astext_type=sa.Text()),
            type_=postgresql.JSONB(astext_type=sa.Text()),
            existing_nullable=False,
            existing_server_default=sa.text("'{}'::json"),
        )
        batch_op.alter_column(
            "sensors_to_show_as_kpis",
            existing_type=postgresql.JSON(astext_type=sa.Text()),
            type_=postgresql.JSONB(astext_type=sa.Text()),
            existing_nullable=False,
            existing_server_default=sa.text("'[]'::json"),
        )

    with op.batch_alter_table("sensor", schema=None) as batch_op:
        batch_op.alter_column(
            "attributes",
            existing_type=postgresql.JSON(astext_type=sa.Text()),
            type_=postgresql.JSONB(astext_type=sa.Text()),
            existing_nullable=False,
        )


def downgrade():
    with op.batch_alter_table("sensor", schema=None) as batch_op:
        batch_op.alter_column(
            "attributes",
            existing_type=postgresql.JSONB(astext_type=sa.Text()),
            type_=postgresql.JSON(astext_type=sa.Text()),
            existing_nullable=False,
        )

    with op.batch_alter_table("generic_asset", schema=None) as batch_op:
        batch_op.alter_column(
            "sensors_to_show_as_kpis",
            existing_type=postgresql.JSONB(astext_type=sa.Text()),
            type_=postgresql.JSON(astext_type=sa.Text()),
            existing_nullable=False,
            existing_server_default=sa.text("'[]'::json"),
        )
        batch_op.alter_column(
            "flex_model",
            existing_type=postgresql.JSONB(astext_type=sa.Text()),
            type_=postgresql.JSON(astext_type=sa.Text()),
            existing_nullable=False,
            existing_server_default=sa.text("'{}'::json"),
        )
        batch_op.alter_column(
            "flex_context",
            existing_type=postgresql.JSONB(astext_type=sa.Text()),
            type_=postgresql.JSON(astext_type=sa.Text()),
            existing_nullable=False,
            existing_server_default=sa.text("'{}'::json"),
        )
        batch_op.alter_column(
            "sensors_to_show",
            existing_type=postgresql.JSONB(astext_type=sa.Text()),
            type_=postgresql.JSON(astext_type=sa.Text()),
            existing_nullable=False,
            existing_server_default=sa.text("'[]'::json"),
        )
        batch_op.alter_column(
            "attributes",
            existing_type=postgresql.JSONB(astext_type=sa.Text()),
            type_=postgresql.JSON(astext_type=sa.Text()),
            existing_nullable=False,
        )

    with op.batch_alter_table("data_source", schema=None) as batch_op:
        batch_op.alter_column(
            "attributes",
            existing_type=postgresql.JSONB(astext_type=sa.Text()),
            type_=postgresql.JSON(astext_type=sa.Text()),
            existing_nullable=False,
            existing_server_default=sa.text("'{}'::json"),
        )
