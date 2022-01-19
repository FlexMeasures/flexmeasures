from typing import Optional

import click
from flask import current_app as app
from flask.cli import with_appcontext

from flexmeasures.data import db
from flexmeasures.data.models.user import Account, AccountRole, RolesAccounts, User
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.scripts.data_gen import get_affected_classes
from flexmeasures.data.services.users import find_user_by_email, delete_user


@click.group("delete")
def fm_delete_data():
    """FlexMeasures: Delete data."""


@fm_delete_data.command("account-role")
@with_appcontext
@click.option("--name", required=True)
def delete_account_role(name: str):
    """
    Delete an account role.
    If it has accounts connected, print them before deleting the connection.
    """
    role: AccountRole = AccountRole.query.filter_by(name=name).one_or_none()
    if role is None:
        click.echo(f"Account role '{name}' does not exist.")
        raise click.Abort
    accounts = role.accounts.all()
    if len(accounts) > 0:
        click.echo(
            f"The following accounts have role '{role.name}': {','.join([a.name for a in accounts])}. Removing this role from them ..."
        )
        for account in accounts:
            account.account_roles.remove(role)
    db.session.delete(role)
    db.session.commit()
    print(f"Account role '{name}'' has been deleted.")


@fm_delete_data.command("account")
@with_appcontext
@click.option("--id", type=int)
@click.option(
    "--force/--no-force", default=False, help="Skip warning about consequences."
)
def delete_account(id: int, force: bool):
    """
    Delete an account, including their users & data.
    """
    account: Account = db.session.query(Account).get(id)
    if account is None:
        print(f"Account with ID '{id}' does not exist.")
        raise click.Abort
    if not force:
        prompt = f"Delete account '{account.name}', including generic assets, users and all their data?\n"
        users = User.query.filter(User.account_id == id).all()
        if users:
            prompt += "Affected users: " + ",".join([u.username for u in users]) + "\n"
        generic_assets = GenericAsset.query.filter(GenericAsset.account_id == id).all()
        if generic_assets:
            prompt += (
                "Affected generic assets: "
                + ",".join([ga.name for ga in generic_assets])
                + "\n"
            )
        if not click.confirm(prompt):
            raise click.Abort()
    for user in account.users:
        print(f"Deleting user {user} (and assets & data) ...")
        delete_user(user)
    for role_account_association in RolesAccounts.query.filter_by(
        account_id=account.id
    ).all():
        role = AccountRole.query.get(role_account_association.role_id)
        print(
            f"Deleting association of account {account.name} and role {role.name} ..."
        )
        db.session.delete(role_account_association)
    for asset in account.generic_assets:
        print(f"Deleting generic asset {asset} (and sensors & beliefs) ...")
        db.session.delete(asset)
    account_name = account.name
    db.session.delete(account)
    db.session.commit()
    print(f"Account {account_name} has been deleted.")


@fm_delete_data.command("user")
@with_appcontext
@click.option("--email")
@click.option(
    "--force/--no-force", default=False, help="Skip warning about consequences."
)
def delete_user_and_data(email: str, force: bool):
    """
    Delete a user & also their assets and data.
    """
    if not force:
        # TODO: later, when assets belong to accounts, remove this.
        prompt = f"Delete user '{email}', including all their assets and data?"
        if not click.confirm(prompt):
            raise click.Abort()
    the_user = find_user_by_email(email)
    if the_user is None:
        print(f"Could not find user with email address '{email}' ...")
        return
    delete_user(the_user)
    app.db.session.commit()


def confirm_deletion(
    structure: bool = False,
    data: bool = False,
    is_by_id: bool = False,
):
    affected_classes = get_affected_classes(structure, data)
    prompt = "This deletes all %s entries from %s.\nDo you want to continue?" % (
        " and ".join(
            ", ".join(
                [affected_class.__tablename__ for affected_class in affected_classes]
            ).rsplit(", ", 1)
        ),
        app.db.engine,
    )
    if is_by_id:
        prompt = prompt.replace(" all ", " ")
    if not click.confirm(prompt):
        raise click.Abort()


@fm_delete_data.command("structure")
@with_appcontext
@click.option(
    "--force/--no-force", default=False, help="Skip warning about consequences."
)
def delete_structure(force):
    """
    Delete all structural (non time-series) data like assets (types),
    markets (types) and weather sensors (types) and users.

    TODO: This could in our future data model (currently in development) be replaced by
    `flexmeasures delete generic-asset-type`, `flexmeasures delete generic-asset`
    and `flexmeasures delete sensor`.
    """
    if not force:
        confirm_deletion(structure=True)
    from flexmeasures.data.scripts.data_gen import depopulate_structure

    depopulate_structure(app.db)


@fm_delete_data.command("measurements")
@with_appcontext
@click.option(
    "--sensor-id",
    type=int,
    help="Delete (time series) data for a single sensor only. Follow up with the sensor's ID.",
)
@click.option(
    "--force/--no-force", default=False, help="Skip warning about consequences."
)
def delete_measurements(
    force: bool,
    sensor_id: Optional[int] = None,
):
    """Delete measurements (ex-post beliefs, i.e. with belief_horizon <= 0)."""
    if not force:
        confirm_deletion(data=True, is_by_id=sensor_id is not None)
    from flexmeasures.data.scripts.data_gen import depopulate_measurements

    depopulate_measurements(app.db, sensor_id)


@fm_delete_data.command("prognoses")
@with_appcontext
@click.option(
    "--force/--no-force", default=False, help="Skip warning about consequences."
)
@click.option(
    "--sensor-id",
    type=int,
    help="Delete (time series) data for a single sensor only. Follow up with the sensor's ID. ",
)
def delete_prognoses(
    force: bool,
    sensor_id: Optional[int] = None,
):
    """Delete forecasts and schedules (ex-ante beliefs, i.e. with belief_horizon > 0)."""
    if not force:
        confirm_deletion(data=True, is_by_id=sensor_id is not None)
    from flexmeasures.data.scripts.data_gen import depopulate_prognoses

    depopulate_prognoses(app.db, sensor_id)


app.cli.add_command(fm_delete_data)
