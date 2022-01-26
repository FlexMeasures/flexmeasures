"""add account table

Revision ID: 994170c26bc6
Revises: b6d49ed7cceb
Create Date: 2021-08-11 19:21:07.083253

"""
from typing import List, Tuple, Optional
import os
import json

from alembic import context, op
import sqlalchemy as sa
from sqlalchemy import orm
import inflection

from flexmeasures.data.models.user import Account, User
from flexmeasures.data.models.time_series import Sensor


# revision identifiers, used by Alembic.
revision = "994170c26bc6"
down_revision = "b6d49ed7cceb"
branch_labels = None
depends_on = None
asset_ownership_backup_script = "generic_asset_fm_user_ownership.sql"

t_assets = sa.Table(
    "asset",
    sa.MetaData(),
    sa.Column("id"),
    sa.Column("owner_id"),
)

t_generic_assets = sa.Table(
    "generic_asset",
    sa.MetaData(),
    sa.Column("id"),
    sa.Column("name"),
    sa.Column("generic_asset_type_id"),
)


def upgrade():
    """
    Add account table.
    1. Users need an account. You can pass this info in (user ID to account name) like this:
       flexmeasures db upgrade +1 -x '{"1": "One account", "2": "Bccount", "4": "Bccount"}'
       Note that user IDs are strings here, as this is a JSON array.
       The +1 makes sure we only upgrade by 1 revision, as these arguments are only meant to be used by this upgrade function.
       Users not mentioned here get an account derived from their email address' main domain, capitalized (info@company.com becomes "Company")
    2. The ownership of a generic_asset now goes to account.
       Here we fill in the user's new account (see point 1).
       (we save a backup of the generic_asset.owner_id info which linked to fm_user)
       The old-style asset's ownership remains in place for now! Our code will keep it consistent, until we have completed the move.
    """
    backup_generic_asset_user_associations()

    upgrade_schema()
    upgrade_data()

    op.alter_column("fm_user", "account_id", nullable=False)
    op.drop_column("generic_asset", "owner_id")


def downgrade():
    downgrade_schema()
    downgrade_data()


def upgrade_schema():
    op.create_table(
        "account",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("account_pkey")),
        sa.UniqueConstraint("name", name=op.f("account_name_key")),
    )
    op.add_column("fm_user", sa.Column("account_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f("fm_user_account_id_account_fkey"),
        "fm_user",
        "account",
        ["account_id"],
        ["id"],
    )
    op.add_column("generic_asset", sa.Column("account_id", sa.Integer(), nullable=True))
    op.drop_constraint(
        "generic_asset_owner_id_fm_user_fkey", "generic_asset", type_="foreignkey"
    )
    op.create_foreign_key(
        op.f("generic_asset_account_id_account_fkey"),
        "generic_asset",
        "account",
        ["account_id"],
        ["id"],
        ondelete="CASCADE",
    )


def upgrade_data():
    # add custom accounts
    user_account_mappings = context.get_x_argument()
    connection = op.get_bind()
    session = orm.Session(bind=connection)
    for i, user_account_map in enumerate(user_account_mappings):
        print(user_account_map)
        user_account_dict = json.loads(user_account_map)
        for user_id, account_name in user_account_dict.items():
            print(
                f"Linking user {user_id} to account {account_name} (as from custom param) ..."
            )
            account = session.query(Account).filter_by(name=account_name).one_or_none()
            if account is None:
                print(f"need to create account {account_name} ...")
                account = Account(name=account_name)
                session.add(account)
                session.flush()
            user = session.query(User).filter_by(id=user_id).one_or_none()
            if not user:
                raise ValueError(f"User with ID {user_id} does not exist!")
            user.account_id = account.id

    # Make sure each existing user has an account
    for user in session.query(User).all():
        if user.account_id is None:
            domain = user.email.split("@")[-1].rsplit(".", maxsplit=1)[0]
            main_domain = domain.rsplit(".", maxsplit=1)[-1]
            account_name = inflection.titleize(main_domain)
            print(f"Linking user {user.id} to account {account_name} ...")
            account = session.query(Account).filter_by(name=account_name).one_or_none()
            if account is None:
                print(f"need to create account {account_name} ...")
                account = Account(name=account_name)
                session.add(account)
                session.flush()
            user.account_id = account.id

    # For all generic assets, set the user's account
    # We query the db for old ownership directly, as the generic asset code already points to account
    asset_ownership_db = _generic_asset_ownership()
    generic_asset_results = connection.execute(
        sa.select(
            [
                t_generic_assets.c.id,
                t_generic_assets.c.name,
                t_generic_assets.c.generic_asset_type_id,
            ]
        )
    ).all()
    for ga_id, ga_name, ga_generic_asset_type_id in generic_asset_results:
        # 1. first look into GenericAsset ownership
        old_owner_id = _get_old_owner_id_from_db_result(asset_ownership_db, ga_id)
        user = (
            session.query(User).get(old_owner_id) if old_owner_id is not None else None
        )
        # 2. Otherwise, then try the old-style Asset's ownership (via Sensor)
        if user is None:
            sensor = (
                session.query(Sensor).filter_by(generic_asset_id=ga_id).one_or_none()
            )
            if sensor is None:
                raise ValueError(
                    f"GenericAsset {ga_id} ({ga_name}) does not have an assorted sensor. Please investigate ..."
                )
            asset_results = connection.execute(
                sa.select([t_assets.c.owner_id]).where(t_assets.c.id == sensor.id)
            ).one_or_none()
            if asset_results is None:
                print(
                    f"Generic asset {ga_name} does not have an asset associated, probably because it's of type {ga_generic_asset_type_id}."
                )
            else:
                user = session.query(User).get(asset_results[0])
        if user is not None:
            connection.execute(
                sa.update(t_generic_assets)
                .where(t_generic_assets.c.id == ga_id)
                .values(account_id=user.account.id)
            )
    session.commit()


def downgrade_schema():
    op.add_column(
        "generic_asset",
        sa.Column("owner_id", sa.INTEGER(), autoincrement=False, nullable=True),
    )
    op.drop_constraint(
        op.f("generic_asset_account_id_account_fkey"),
        "generic_asset",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "generic_asset_owner_id_fm_user_fkey",
        "generic_asset",
        "fm_user",
        ["owner_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_column("generic_asset", "account_id")
    op.drop_constraint(
        op.f("fm_user_account_id_account_fkey"), "fm_user", type_="foreignkey"
    )
    op.drop_column("fm_user", "account_id")
    op.drop_table("account")


def downgrade_data():
    if os.path.exists(asset_ownership_backup_script):
        print(
            f"Re-applying previous asset ownership from {asset_ownership_backup_script} ..."
        )
        connection = op.get_bind()
        session = orm.Session(bind=connection)
        with open(asset_ownership_backup_script, "r") as bckp_file:
            for statement in bckp_file.readlines():
                connection.execute(statement)
        session.commit()
    else:
        print(f"Could not find backup script {asset_ownership_backup_script} ...")
        print("Previous asset ownership information is probably lost.")


def backup_generic_asset_user_associations():
    asset_ownership_results = _generic_asset_ownership()
    backed_up_ownerships = 0
    with open(asset_ownership_backup_script, "w") as bckp_file:
        for aid, oid in asset_ownership_results:
            if oid is None:
                oid = "null"
            bckp_file.write(
                f"UPDATE generic_asset SET owner_id = {oid} WHERE id = {aid};\n"
            )
            backed_up_ownerships += 1

    if backed_up_ownerships > 0:
        print("Your generic_asset.owner_id associations are being dropped!")
        print(
            f"We saved UPDATE statements to put them back in {asset_ownership_backup_script}."
        )


def _generic_asset_ownership() -> List[Tuple[int, int]]:
    t_asset_owners = sa.Table(
        "generic_asset",
        sa.MetaData(),
        sa.Column("id", sa.Integer),
        sa.Column("owner_id", sa.Integer),
    )

    # Use SQLAlchemy's connection and transaction to go through the data
    connection = op.get_bind()

    # Select all existing ids that need migrating, while keeping names intact
    asset_ownership_results = connection.execute(
        sa.select(
            [
                t_asset_owners.c.id,
                t_asset_owners.c.owner_id,
            ]
        )
    ).fetchall()
    return asset_ownership_results


def _get_old_owner_id_from_db_result(
    generic_asset_ownership, asset_id
) -> Optional[int]:
    for aid, oid in generic_asset_ownership:
        if aid == asset_id:
            return oid
    return None
