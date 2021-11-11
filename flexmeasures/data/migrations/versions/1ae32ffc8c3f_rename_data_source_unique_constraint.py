"""Rename data source unique constraint

Revision ID: 1ae32ffc8c3f
Revises: 30fe2267e7d5
Create Date: 2021-11-11 16:54:09.302274

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "1ae32ffc8c3f"
down_revision = "30fe2267e7d5"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint(
        "_data_source_name_user_id_model_version_key", "data_source", type_="unique"
    )
    op.create_unique_constraint(
        op.f("data_source_name_key"),
        "data_source",
        ["name", "user_id", "model", "version"],
    )


def downgrade():
    op.drop_constraint(op.f("data_source_name_key"), "data_source", type_="unique")
    op.create_unique_constraint(
        "_data_source_name_user_id_model_version_key",
        "data_source",
        ["name", "user_id", "model", "version"],
    )
