"""Add account_id to data_source table

Revision ID: 9877450113f6
Revises: 8b62f8129f34
Create Date: 2025-01-15 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "9877450113f6"
down_revision = "8b62f8129f34"
branch_labels = None
depends_on = None

# Minimal table definitions for the data migration (SQLAlchemy Core only, no ORM)
t_data_source = sa.Table(
    "data_source",
    sa.MetaData(),
    sa.Column("id", sa.Integer),
    sa.Column("user_id", sa.Integer),
    sa.Column("account_id", sa.Integer),
)

t_fm_user = sa.Table(
    "fm_user",
    sa.MetaData(),
    sa.Column("id", sa.Integer),
    sa.Column("account_id", sa.Integer),
)


def upgrade():
    # 1. Add the account_id column (nullable)
    with op.batch_alter_table("data_source", schema=None) as batch_op:
        batch_op.add_column(sa.Column("account_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            op.f("data_source_account_id_account_fkey"),
            "account",
            ["account_id"],
            ["id"],
        )

    # 2. Data migration: populate account_id from the related user's account
    connection = op.get_bind()
    rows = connection.execute(
        sa.select(t_data_source.c.id, t_data_source.c.user_id).where(
            t_data_source.c.user_id.isnot(None)
        )
    ).fetchall()

    for ds_id, user_id in rows:
        user_row = connection.execute(
            sa.select(t_fm_user.c.account_id).where(t_fm_user.c.id == user_id)
        ).fetchone()
        if user_row is not None and user_row[0] is not None:
            connection.execute(
                sa.update(t_data_source)
                .where(t_data_source.c.id == ds_id)
                .values(account_id=user_row[0])
            )

    # 3. Drop old UniqueConstraint and recreate it with account_id included
    with op.batch_alter_table("data_source", schema=None) as batch_op:
        batch_op.drop_constraint("data_source_name_key", type_="unique")
        batch_op.create_unique_constraint(
            "data_source_name_key",
            ["name", "user_id", "account_id", "model", "version", "attributes_hash"],
        )


def downgrade():
    # 1. Restore the original UniqueConstraint without account_id
    with op.batch_alter_table("data_source", schema=None) as batch_op:
        batch_op.drop_constraint("data_source_name_key", type_="unique")
        batch_op.create_unique_constraint(
            "data_source_name_key",
            ["name", "user_id", "model", "version", "attributes_hash"],
        )

    # 2. Drop the account_id column and its FK
    with op.batch_alter_table("data_source", schema=None) as batch_op:
        batch_op.drop_constraint(
            op.f("data_source_account_id_account_fkey"), type_="foreignkey"
        )
        batch_op.drop_column("account_id")
