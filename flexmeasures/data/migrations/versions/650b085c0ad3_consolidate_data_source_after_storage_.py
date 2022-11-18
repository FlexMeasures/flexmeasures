"""Consolidate data source after storage schedulers merged

Revision ID: 650b085c0ad3
Revises: 30f7b63069e1
Create Date: 2022-11-16 07:07:44.281943

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "650b085c0ad3"
down_revision = "30f7b63069e1"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "Update data_source set version='1', model='StorageScheduler' where name = 'Seita' and type='scheduling script';"
    )


def downgrade():
    op.execute(
        "Update data_source set version=null, model=null where name = 'Seita' and type='scheduling script' and version='1' and model='StorageScheduler';"
    )
