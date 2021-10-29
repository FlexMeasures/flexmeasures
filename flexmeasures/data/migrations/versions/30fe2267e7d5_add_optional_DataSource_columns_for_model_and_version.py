"""add optional DataSource columns for model and version

Revision ID: 30fe2267e7d5
Revises: 96f2db5bed30
Create Date: 2021-10-11 10:54:24.348371

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "30fe2267e7d5"
down_revision = "96f2db5bed30"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "data_source", sa.Column("model", sa.String(length=80), nullable=True)
    )
    op.add_column(
        "data_source", sa.Column("version", sa.String(length=17), nullable=True)
    )
    op.create_unique_constraint(
        "_data_source_name_user_id_model_version_key",
        "data_source",
        ["name", "user_id", "model", "version"],
    )


def downgrade():
    op.drop_constraint(
        "_data_source_name_user_id_model_version_key", "data_source", type_="unique"
    )
    op.drop_column("data_source", "version")
    op.drop_column("data_source", "model")
