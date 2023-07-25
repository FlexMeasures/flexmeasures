"""add attribute column to data source

Revision ID: 2ac7fb39ce0c
Revises: d814c0688ae0
Create Date: 2023-06-05 23:41:31.788961

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "2ac7fb39ce0c"
down_revision = "d814c0688ae0"
branch_labels = None
depends_on = None


def upgrade():
    # add the column `attributes` to the table `data_source`
    op.add_column(
        "data_source",
        sa.Column("attributes", sa.JSON(), nullable=True, default={}),
    )

    # add the column `attributes_hash` to the table `data_source`
    op.add_column(
        "data_source",
        sa.Column("attributes_hash", sa.LargeBinary(length=256), nullable=True),
    )

    # remove previous uniqueness constraint and add a new that takes attributes_hash into account
    op.drop_constraint(op.f("data_source_name_key"), "data_source", type_="unique")
    op.create_unique_constraint(
        "data_source_name_key",
        "data_source",
        ["name", "user_id", "model", "version", "attributes_hash"],
    )


def downgrade():

    op.drop_constraint("data_source_name_key", "data_source", type_="unique")
    op.create_unique_constraint(
        "data_source_name_key",
        "data_source",
        ["name", "user_id", "model", "version"],
    )

    op.drop_column("data_source", "attributes")
    op.drop_column("data_source", "attributes_hash")
