"""add user.fs_uniquifier for faster auth tokens

Revision ID: b797328ac32d
Revises: 3db3e71d101d
Create Date: 2020-08-24 19:01:04.337956

"""

import uuid

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b797328ac32d"
down_revision = "3db3e71d101d"
branch_labels = None
depends_on = None


unique_key_name = "bvp_users_fs_uniquifier_key"


def upgrade():
    """
    The add_column and create_unique_constraint commands are
    auto generated by Alembic. The former was adjusted according
    to https://flask-security-too.readthedocs.io/en/stable/changelog.html#new-fast-authentication-token-implementatioadjust! ###
    which also suggested the added code to update existing user rows.
    """

    # Here, we changed nullable to True so we can then update existing rows
    op.add_column(
        "bvp_users", sa.Column("fs_uniquifier", sa.String(length=64), nullable=True)
    )

    # Now update existing rows with unique fs_uniquifier
    user_table = sa.Table(
        "bvp_users",
        sa.MetaData(),
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("fs_uniquifier", sa.String),
    )
    conn = op.get_bind()
    for row in conn.execute(sa.select(*[user_table.c.id])):
        conn.execute(
            user_table.update()
            .values(fs_uniquifier=uuid.uuid4().hex)
            .where(user_table.c.id == row["id"])
        )

    # Finally - set nullable back to False
    op.alter_column("bvp_users", "fs_uniquifier", nullable=False)

    op.create_unique_constraint(unique_key_name, "bvp_users", ["fs_uniquifier"])


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint(unique_key_name, "bvp_users", type_="unique")
    op.drop_column("bvp_users", "fs_uniquifier")
    # ### end Alembic commands ###
