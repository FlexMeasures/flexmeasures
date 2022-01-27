"""CLI Tasks for listing database contents - most useful in development"""

import click
from flask import current_app as app
from flask.cli import with_appcontext
from tabulate import tabulate

from flexmeasures.data.models.user import Account, User
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.time_series import Sensor


@click.group("show")
def fm_show_data():
    """FlexMeasures: Show data."""


@fm_show_data.command("accounts")
@with_appcontext
def list_accounts():
    """
    List all accounts on this FlexMeasures instance.
    """
    accounts = Account.query.all()
    if not accounts:
        click.echo("No accounts created yet.")
        raise click.Abort
    click.echo("All accounts on this FlexMeasures instance:\n ")
    account_data = [
        (
            account.id,
            account.name,
            GenericAsset.query.filter(GenericAsset.account_id == account.id).count(),
        )
        for account in accounts
    ]
    print(tabulate(account_data, headers=["Id", "Name", "Assets"]))


@fm_show_data.command("account")
@with_appcontext
@click.option("--account-id", type=int, required=True)
def show_account(account_id):
    """
    Show information about an account, including users and assets.
    """
    account: Account = Account.query.get(account_id)
    if not account:
        click.echo(f"No account with id {account_id} known.")
        raise click.Abort

    click.echo(f"========{len(account.name) * '='}==========")
    click.echo(f"Account {account.name} (ID:{account.id}):")
    click.echo(f"========{len(account.name) * '='}==========\n")

    if account.account_roles:
        click.echo(
            f"Account role(s): {','.join([role.name for role in account.account_roles])}"
        )
    else:
        click.echo("Account has no roles.")
    click.echo()

    users = User.query.filter_by(account_id=account_id).all()
    if not users:
        click.echo("No users in account ...")
    else:
        click.echo("All users:\n ")
        user_data = [
            (
                user.id,
                user.username,
                user.email,
                user.last_login_at,
                "".join([role.name for role in user.roles]),
            )
            for user in users
        ]
        print(
            tabulate(user_data, headers=["Id", "Name", "Email", "Last Login", "Roles"])
        )

    click.echo()
    assets = GenericAsset.query.filter_by(account_id=account_id).all()
    if not assets:
        click.echo("No assets in account ...")
    else:
        click.echo("All assets:\n ")
        asset_data = [
            (asset.id, asset.name, asset.generic_asset_type.name, asset.location)
            for asset in assets
        ]
        print(tabulate(asset_data, headers=["Id", "Name", "Type", "Location"]))


@fm_show_data.command("asset")
@with_appcontext
@click.option("--asset-id", type=int, required=True)
def show_generic_asset(asset_id):
    """
    Show asset info and list sensors
    """
    asset = GenericAsset.query.get(asset_id)
    if not asset:
        click.echo(f"No asset with id {asset_id} known.")
        raise click.Abort

    click.echo(f"======{len(asset.name) * '='}==========")
    click.echo(f"Asset {asset.name} (ID:{asset.id}):")
    click.echo(f"======{len(asset.name) * '='}==========\n")

    asset_data = [
        (
            asset.generic_asset_type.name,
            asset.location,
            "".join([f"{k}:{v}\n" for k, v in asset.attributes.items()]),
        )
    ]
    print(tabulate(asset_data, headers=["Type", "Location", "Attributes"]))

    click.echo()
    sensors = Sensor.query.filter_by(generic_asset_id=asset_id).all()
    if not sensors:
        click.echo("No sensors in asset ...")
        raise click.Abort
    click.echo("All sensors in asset:\n ")
    sensor_data = [
        (
            sensor.id,
            sensor.name,
            sensor.unit,
            sensor.event_resolution,
            sensor.timezone,
            "".join([f"{k}:{v}\n" for k, v in sensor.attributes.items()]),
        )
        for sensor in sensors
    ]
    print(
        tabulate(
            sensor_data,
            headers=["Id", "Name", "Unit", "Resolution", "Timezone", "Attributes"],
        )
    )


app.cli.add_command(fm_show_data)
