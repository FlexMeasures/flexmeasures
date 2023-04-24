"""Rename DataSource types for forecasters and schedulers

Revision ID: c41beee0c904
Revises: 650b085c0ad3
Create Date: 2022-11-30 21:33:09.046751

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "c41beee0c904"
down_revision = "650b085c0ad3"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "update data_source set type='scheduler' where type='scheduling script';"
    )
    op.execute(
        "update data_source set type='forecaster' where type='forecasting script';"
    )


def downgrade():
    op.execute(
        "update data_source set type='scheduling script' where type='scheduler';"
    )
    op.execute(
        "update data_source set type='forecasting script' where type='forecaster';"
    )
