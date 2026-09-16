"""Added primary and secondary color field to account model

Revision ID: 4b5aa7856932
Revises: 3eb0564948ca
Create Date: 2024-08-08 13:38:17.197805

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "4b5aa7856932"
down_revision = "3eb0564948ca"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("account", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("primary_color", sa.String(length=7), nullable=True)
        )
        batch_op.add_column(
            sa.Column("secondary_color", sa.String(length=7), nullable=True)
        )


def downgrade():
    with op.batch_alter_table("account", schema=None) as batch_op:
        batch_op.drop_column("secondary_color")
        batch_op.drop_column("primary_color")
