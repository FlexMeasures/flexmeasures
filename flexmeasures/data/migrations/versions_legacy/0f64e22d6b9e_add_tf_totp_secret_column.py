"""Add tf_totp_secret column

Revision ID: 0f64e22d6b9e
Revises: ece7fb4207ed
Create Date: 2025-06-23 23:46:19.461406

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session
from passlib.totp import TOTP

# revision identifiers, used by Alembic.
revision = "0f64e22d6b9e"
down_revision = "ece7fb4207ed"
branch_labels = None
depends_on = None


def upgrade():
    # Add the columns first
    with op.batch_alter_table("fm_user", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "tf_totp_secret", sa.Text(), nullable=True
            )  # Using Text to store JSON
        )
        batch_op.add_column(
            sa.Column(
                "tf_primary_method",
                sa.String(length=255),
                nullable=True,
                server_default="email",
            )
        )

    # Get the table metadata for SQLAlchemy
    bind = op.get_bind()
    session = Session(bind=bind)
    fm_user = sa.Table(
        "fm_user",
        sa.MetaData(),
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("email", sa.String(255)),
        sa.Column("tf_totp_secret", sa.Text()),
        autoload_with=bind,
    )

    # Generate unique TOTP config for each user
    for user in session.execute(sa.select(fm_user)):
        # Generate a new TOTP config using passlib
        totp = TOTP.new()
        json_config = totp.to_json()

        # Update the user record with the JSON config
        session.execute(
            fm_user.update()
            .where(fm_user.c.id == user.id)
            .values(tf_totp_secret=json_config)
        )

    # Commit changes
    session.commit()


def downgrade():
    with op.batch_alter_table("fm_user", schema=None) as batch_op:
        batch_op.drop_column("tf_totp_secret")
        batch_op.drop_column("tf_primary_method")
