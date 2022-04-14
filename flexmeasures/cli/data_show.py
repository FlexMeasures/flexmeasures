"""CLI Tasks for listing database contents - most useful in development"""

from typing import Optional, List
from datetime import datetime, timedelta

import click
from flask import current_app as app
from flask.cli import with_appcontext
from tabulate import tabulate
from humanize import naturaldelta, naturaltime
import uniplot

from flexmeasures.data.models.user import Account, AccountRole, User, Role
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.data.schemas.generic_assets import GenericAssetIdField
from flexmeasures.data.schemas.sensors import SensorIdField
from flexmeasures.data.schemas.account import AccountIdField
from flexmeasures.data.schemas.sources import DataSourceIdField
from flexmeasures.data.schemas.times import AwareDateTimeField, DurationField


@click.group("show")
def fm_show_data():
    """FlexMeasures: Show data."""


@fm_show_data.command("accounts")
@with_appcontext
def list_accounts():
    """
    List all accounts on this FlexMeasures instance.
    """
    accounts = Account.query.order_by(Account.name).all()
    if not accounts:
        click.echo("No accounts created yet.")
        return
    click.echo("All accounts on this FlexMeasures instance:\n ")
    account_data = [
        (
            account.id,
            account.name,
            GenericAsset.query.filter(GenericAsset.account_id == account.id).count(),
        )
        for account in accounts
    ]
    click.echo(tabulate(account_data, headers=["Id", "Name", "Assets"]))


@fm_show_data.command("roles")
@with_appcontext
def list_roles():
    """
    Show available account an user roles
    """
    account_roles = AccountRole.query.order_by(AccountRole.name).all()
    if not account_roles:
        click.echo("No account roles created yet.")
        return
    click.echo("Account roles:\n")
    click.echo(
        tabulate(
            [(r.id, r.name, r.description) for r in account_roles],
            headers=["Id", "Name", "Description"],
        )
    )
    click.echo()
    user_roles = Role.query.order_by(Role.name).all()
    if not user_roles:
        click.echo("No user roles created yet, not even admin.")
        return
    click.echo("User roles:\n")
    click.echo(
        tabulate(
            [(r.id, r.name, r.description) for r in user_roles],
            headers=["Id", "Name", "Description"],
        )
    )


@fm_show_data.command("account")
@with_appcontext
@click.option("--id", "account", type=AccountIdField(), required=True)
def show_account(account):
    """
    Show information about an account, including users and assets.
    """
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

    users = User.query.filter_by(account_id=account.id).order_by(User.username).all()
    if not users:
        click.echo("No users in account ...")
    else:
        click.echo("All users:\n ")
        user_data = [
            (
                user.id,
                user.username,
                user.email,
                naturaltime(user.last_login_at),
                "".join([role.name for role in user.roles]),
            )
            for user in users
        ]
        click.echo(
            tabulate(user_data, headers=["Id", "Name", "Email", "Last Login", "Roles"])
        )

    click.echo()
    assets = (
        GenericAsset.query.filter_by(account_id=account.id)
        .order_by(GenericAsset.name)
        .all()
    )
    if not assets:
        click.echo("No assets in account ...")
    else:
        click.echo("All assets:\n ")
        asset_data = [
            (asset.id, asset.name, asset.generic_asset_type.name, asset.location)
            for asset in assets
        ]
        click.echo(tabulate(asset_data, headers=["Id", "Name", "Type", "Location"]))


@fm_show_data.command("asset-types")
@with_appcontext
def list_asset_types():
    """
    Show available asset types
    """
    asset_types = GenericAssetType.query.order_by(GenericAssetType.name).all()
    if not asset_types:
        click.echo("No asset types created yet.")
        return
    click.echo(
        tabulate(
            [(t.id, t.name, t.description) for t in asset_types],
            headers=["Id", "Name", "Description"],
        )
    )


@fm_show_data.command("asset")
@with_appcontext
@click.option("--id", "asset", type=GenericAssetIdField(), required=True)
def show_generic_asset(asset):
    """
    Show asset info and list sensors
    """
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
    click.echo(tabulate(asset_data, headers=["Type", "Location", "Attributes"]))

    click.echo()
    sensors = (
        Sensor.query.filter_by(generic_asset_id=asset.id).order_by(Sensor.name).all()
    )
    if not sensors:
        click.echo("No sensors in asset ...")
        return
    click.echo("All sensors in asset:\n ")
    sensor_data = [
        (
            sensor.id,
            sensor.name,
            sensor.unit,
            naturaldelta(sensor.event_resolution),
            sensor.timezone,
            "".join([f"{k}:{v}\n" for k, v in sensor.attributes.items()]),
        )
        for sensor in sensors
    ]
    click.echo(
        tabulate(
            sensor_data,
            headers=["Id", "Name", "Unit", "Resolution", "Timezone", "Attributes"],
        )
    )


@fm_show_data.command("data-sources")
@with_appcontext
def list_data_sources():
    """
    Show available data sources
    """
    sources = DataSource.query.order_by(DataSource.name).all()
    if not sources:
        click.echo("No data sources created yet.")
        return
    click.echo(
        tabulate(
            [(s.id, s.name, s.type, s.user_id, s.model, s.version) for s in sources],
            headers=["Id", "Name", "Type", "User Id", "Model", "Version"],
        )
    )


@fm_show_data.command("beliefs")
@with_appcontext
@click.option(
    "--sensor-id",
    "sensors",
    required=True,
    multiple=True,
    type=SensorIdField(),
    help="ID of sensor(s). This argument can be given multiple times.",
)
@click.option(
    "--start",
    "start",
    type=AwareDateTimeField(),
    required=True,
    help="Plot starting at this datetime. Follow up with a timezone-aware datetime in ISO 6801 format.",
)
@click.option(
    "--duration",
    "duration",
    type=DurationField(),
    required=True,
    help="Duration of the plot, after --start. Follow up with a duration in ISO 6801 format, e.g. PT1H (1 hour) or PT45M (45 minutes).",
)
@click.option(
    "--belief-time-before",
    "belief_time_before",
    type=AwareDateTimeField(),
    required=False,
    help="Time at which beliefs had been known. Follow up with a timezone-aware datetime in ISO 6801 format.",
)
@click.option(
    "--source-id",
    "source",
    required=False,
    type=DataSourceIdField(),
    help="Source of the beliefs (an existing source id).",
)
def plot_beliefs(
    sensors: List[Sensor],
    start: datetime,
    duration: timedelta,
    belief_time_before: Optional[datetime],
    source: Optional[DataSource],
):
    """
    Show a simple plot of belief data directly in the terminal.
    """
    sensors = list(sensors)
    min_resolution = min([s.event_resolution for s in sensors])

    # query data
    beliefs_by_sensor = TimedBelief.search(
        sensors=sensors,
        event_starts_after=start,
        event_ends_before=start + duration,
        beliefs_before=belief_time_before,
        source=source,
        one_deterministic_belief_per_event=True,
        resolution=min_resolution,
        sum_multiple=False,
    )
    # only keep non-empty
    for s in sensors:
        if beliefs_by_sensor[s.name].empty:
            click.echo(f"No data found for sensor '{s.name}' (Id: {s.id})")
            beliefs_by_sensor.pop(s.name)
            sensors.remove(s)
    if len(beliefs_by_sensor.keys()) == 0:
        click.echo("No data found!")
        raise click.Abort()
    first_df = beliefs_by_sensor[sensors[0].name]

    # Build title
    if len(sensors) == 1:
        title = f"Beliefs for Sensor '{sensors[0].name}' (Id {sensors[0].id}).\n"
    else:
        title = f"Beliefs for Sensor(s) [{','.join([s.name for s in sensors])}], (Id(s): [{','.join([str(s.id) for s in sensors])}]).\n"
    title += f"Data spans {naturaldelta(duration)} and starts at {start}."
    if belief_time_before:
        title += f"\nOnly beliefs made before: {belief_time_before}."
    if source:
        title += f"\nSource: {source.description}"
    title += f"\nThe time resolution (x-axis) is {naturaldelta(min_resolution)}."

    uniplot.plot(
        [
            beliefs.event_value
            for beliefs in [beliefs_by_sensor[sn] for sn in [s.name for s in sensors]]
        ],
        title=title,
        color=True,
        lines=True,
        y_unit=first_df.sensor.unit
        if len(beliefs_by_sensor) == 1
        or all(sensor.unit == first_df.sensor.unit for sensor in sensors)
        else "",
        legend_labels=[s.name for s in sensors],
    )


app.cli.add_command(fm_show_data)
