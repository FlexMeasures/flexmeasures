"""Add tf_totp_secret column

Revision ID: 0f64e22d6b9e
Revises: ece7fb4207ed
Create Date: 2025-06-23 23:46:19.461406

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0f64e22d6b9e"
down_revision = "ece7fb4207ed"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("fm_user", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("tf_totp_secret", sa.String(length=255), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "tf_primary_method",
                sa.String(length=255),
                nullable=True,
                server_default="email",
            )
        )  # Adding a default value of 'email' cos we are working with email for now.


def downgrade():
    with op.batch_alter_table("fm_user", schema=None) as batch_op:
        batch_op.drop_column("tf_totp_secret")
        batch_op.drop_column("tf_primary_method")
