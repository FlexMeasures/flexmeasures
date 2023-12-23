"""Update data sources

Revision ID: c349f52c700d
Revises: ad98460751d9
Create Date: 2023-12-14 10:31:02.612590

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "c349f52c700d"
down_revision = "ad98460751d9"
branch_labels = None
depends_on = None


def upgrade():
    # The name of the data_source should be 120 String, this was not correctly set in an earlier revision of the db.
    with op.batch_alter_table("data_source", schema=None) as batch_op:
        batch_op.alter_column(
            "name",
            existing_type=sa.VARCHAR(length=80),
            type_=sa.String(length=120),
            existing_nullable=False,
        )
        # The attributes were initially set as nullable=False but the migration file did not reflect that.
        # In this migration the model and db are brought in line.
        batch_op.alter_column(
            "attributes",
            existing_type=postgresql.JSON(astext_type=sa.Text()),
            nullable=False,
        )

    # This constraint is renamed to include the full name of the `data_source` table.
    with op.batch_alter_table("timed_belief", schema=None) as batch_op:
        batch_op.drop_constraint(
            "timed_belief_source_id_source_fkey", type_="foreignkey"
        )
        batch_op.create_foreign_key(
            batch_op.f("timed_belief_source_id_data_source_fkey"),
            "data_source",
            ["source_id"],
            ["id"],
        )


def downgrade():
    with op.batch_alter_table("timed_belief", schema=None) as batch_op:
        batch_op.drop_constraint(
            batch_op.f("timed_belief_source_id_data_source_fkey"), type_="foreignkey"
        )
        batch_op.create_foreign_key(
            "timed_belief_source_id_source_fkey",
            "data_source",
            ["source_id"],
            ["id"],
            ondelete="CASCADE",
        )

    with op.batch_alter_table("data_source", schema=None) as batch_op:
        batch_op.alter_column(
            "attributes",
            existing_type=postgresql.JSON(astext_type=sa.Text()),
            nullable=True,
        )
        batch_op.alter_column(
            "name",
            existing_type=sa.String(length=120),
            type_=sa.VARCHAR(length=80),
            existing_nullable=False,
        )
