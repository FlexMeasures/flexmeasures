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
    # add the column `attributes`to the table `data_source`
    op.add_column(
        "data_source",
        sa.Column("attributes", sa.JSON(), nullable=True, default={}),
    )


def downgrade():
    pass
