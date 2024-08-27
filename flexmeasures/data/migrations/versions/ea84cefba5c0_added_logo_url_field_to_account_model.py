"""added logo_url field to account model

Revision ID: ea84cefba5c0
Revises: 4b5aa7856932
Create Date: 2024-08-19 14:07:14.187428

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "ea84cefba5c0"
down_revision = "4b5aa7856932"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("account", schema=None) as batch_op:
        batch_op.add_column(sa.Column("logo_url", sa.String(length=255), nullable=True))


def downgrade():
    with op.batch_alter_table("account", schema=None) as batch_op:
        batch_op.drop_column("logo_url")
