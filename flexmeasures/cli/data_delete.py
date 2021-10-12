from typing import Optional

import click
from flask import current_app as app
from flask.cli import with_appcontext

from flexmeasures.data import db
from flexmeasures.data.models.user import Account, AccountRole, RolesAccounts, User
from flexmeasures.data.models.assets import Power
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.markets import Price
from flexmeasures.data.models.weather import Weather
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
    asset_type: Optional[str] = None,
    is_by_id: bool = False,
):
    affected_classes = get_affected_classes(structure, data)
    if data and asset_type:
        if asset_type == "Asset":
            affected_classes.remove(Price)
            affected_classes.remove(Weather)
        elif asset_type == "Market":
            affected_classes.remove(Power)
            affected_classes.remove(Weather)
        elif asset_type == "WeatherSensor":
            affected_classes.remove(Power)
            affected_classes.remove(Price)
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
    `flexmeasures delete generic-asset-type` and `flexmeasures delete sensor`.
    """
    if not force:
        confirm_deletion(structure=True)
    from flexmeasures.data.scripts.data_gen import depopulate_structure

    depopulate_structure(app.db)


@fm_delete_data.command("measurements")
@with_appcontext
@click.option(
    "--asset-type",
    help="Depopulate (time series) data for a specific generic asset type only."
    "Follow up with Asset, Market or WeatherSensor.",
)
@click.option(
    "--asset-id",
    type=int,
    help="Delete (time series) data for a single asset only. Follow up with the asset's ID. "
    "We still need --asset-type, as well, so we know where to look this ID up.",
)
@click.option(
    "--force/--no-force", default=False, help="Skip warning about consequences."
)
def delete_measurements(
    force: bool,
    asset_type: Optional[str] = None,
    asset_id: Optional[int] = None,
):
    """ Delete measurements (with horizon <= 0)."""
    if not force:
        confirm_deletion(
            data=True, asset_type=asset_type, is_by_id=asset_id is not None
        )
    from flexmeasures.data.scripts.data_gen import depopulate_measurements

    depopulate_measurements(app.db, asset_type, asset_id)


@fm_delete_data.command("prognoses")
@with_appcontext
@click.option(
    "--force/--no-force", default=False, help="Skip warning about consequences."
)
@click.option(
    "--asset-type",
    help="Depopulate (time series) data for a specific generic asset type only. "
    "Follow up with Asset, Market or WeatherSensor.",
)
@click.option(
    "--asset-id",
    type=int,
    help="Depopulate (time series) data for a single asset only. Follow up with the asset's ID. "
    "Use in combination with --asset-type, so we know where to look this name up.",
)
def delete_prognoses(
    force: bool,
    asset_type: Optional[str] = None,
    asset_id: Optional[int] = None,
):
    """Delete forecasts and schedules (forecasts > 0)."""
    if not force:
        confirm_deletion(
            data=True, asset_type=asset_type, is_by_id=asset_id is not None
        )
    from flexmeasures.data.scripts.data_gen import depopulate_prognoses

    depopulate_prognoses(app.db, asset_type, asset_id)


app.cli.add_command(fm_delete_data)
