"""new field last_seen_at in user model

Revision ID: 75f53d2dbfae
Revises: 650b085c0ad3
Create Date: 2022-11-27 00:15:26.403169

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "75f53d2dbfae"
down_revision = "650b085c0ad3"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("fm_user", sa.Column("last_seen_at", sa.DateTime(), nullable=True))
    op.execute(
        "update fm_user set last_seen_at = last_login_at where last_seen_at is null"
    )


def downgrade():
    op.drop_column("fm_user", "last_seen_at")
