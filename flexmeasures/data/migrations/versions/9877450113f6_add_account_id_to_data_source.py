"""Add account_id to data_source table and drop FK constraints for lineage preservation

Adds account_id to data_source (without a DB-level FK constraint, so that referenced
accounts can be deleted while the historical account_id value is preserved for lineage).
Also drops the existing user_id FK constraint for the same reason: when a user is deleted,
the data_source.user_id should remain intact rather than being cascaded or nullified.

Revision ID: 9877450113f6
Revises: 8b62f8129f34
Create Date: 2026-03-24 22:10:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = "9877450113f6"
down_revision = "e26d02ed1621"
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
    # 1. Add the account_id column (nullable, no DB-level FK so lineage is preserved)
    with op.batch_alter_table("data_source", schema=None) as batch_op:
        batch_op.add_column(sa.Column("account_id", sa.Integer(), nullable=True))

    # 2. Data migration: populate account_id from the related user's account.
    #    Use a correlated subquery to avoid N+1 queries and ensure portability.
    connection = op.get_bind()
    connection.execute(
        sa.update(t_data_source)
        .values(
            account_id=sa.select(t_fm_user.c.account_id)
            .where(t_fm_user.c.id == t_data_source.c.user_id)
            .scalar_subquery()
        )
        .where(t_data_source.c.user_id.isnot(None))
    )

    # 3. Drop old UniqueConstraint and recreate it with account_id included
    with op.batch_alter_table("data_source", schema=None) as batch_op:
        batch_op.drop_constraint("data_source_name_key", type_="unique")
        batch_op.create_unique_constraint(
            "data_source_name_key",
            ["name", "user_id", "account_id", "model", "version", "attributes_hash"],
        )

    # 4. Drop the user_id FK constraint so that deleting a user preserves the lineage
    #    reference in data_source rows (no cascade, no SET NULL).
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_fks = inspector.get_foreign_keys("data_source")
    existing_fk_names = [fk["name"] for fk in existing_fks]
    with op.batch_alter_table("data_source", schema=None) as batch_op:
        for fk_name in existing_fk_names:
            if "user_id" in fk_name:
                batch_op.drop_constraint(fk_name, type_="foreignkey")
                break


def downgrade():
    # 1. Re-add the user_id FK constraint
    with op.batch_alter_table("data_source", schema=None) as batch_op:
        batch_op.create_foreign_key(
            "data_source_user_id_fkey",
            "fm_user",
            ["user_id"],
            ["id"],
        )

    # 2. Restore the original UniqueConstraint without account_id
    with op.batch_alter_table("data_source", schema=None) as batch_op:
        batch_op.drop_constraint("data_source_name_key", type_="unique")
        batch_op.create_unique_constraint(
            "data_source_name_key",
            ["name", "user_id", "model", "version", "attributes_hash"],
        )

    # 3. Drop the account_id column
    with op.batch_alter_table("data_source", schema=None) as batch_op:
        batch_op.drop_column("account_id")
