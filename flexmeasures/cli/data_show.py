"""CLI Tasks for listing database contents - most useful in development"""

from typing import Optional, List, Dict
import click
from flask import current_app as app
from flask.cli import with_appcontext
from tabulate import tabulate
from humanize import naturaldelta, naturaltime
import isodate
import uniplot

from flexmeasures.data.models.user import Account, AccountRole, User, Role
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.data.schemas.sources import DataSourceIdField


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
@click.option("--id", "account_id", type=int, required=True)
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

    users = User.query.filter_by(account_id=account_id).order_by(User.username).all()
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
        GenericAsset.query.filter_by(account_id=account_id)
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
@click.option("--id", "asset_id", type=int, required=True)
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
    click.echo(tabulate(asset_data, headers=["Type", "Location", "Attributes"]))

    click.echo()
    sensors = (
        Sensor.query.filter_by(generic_asset_id=asset_id).order_by(Sensor.name).all()
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
    "sensor_ids",
    type=int,
    required=True,
    multiple=True,
    help="ID of sensor(s). This argument can be given multiple times.",
)
@click.option(
    "--from",
    "start_str",
    required=True,
    help="Plot starting at this datetime. Follow up with a timezone-aware datetime in ISO 6801 format.",
)
@click.option(
    "--duration",
    "duration_str",
    required=True,
    help="Duration of the plot, after --from. Follow up with a duration in ISO 6801 format, e.g. PT1H (1 hour) or PT45M (45 minutes).",
)
@click.option(
    "--belief-time-before",
    "belief_time_before_str",
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
    sensor_ids: List[int],
    start_str: str,
    duration_str: str,
    belief_time_before_str: Optional[str],
    source: Optional[DataSource],
):
    """
    Show a simple plot of belief data directly in the terminal.
    """
    # handle required params: sensor, start, duration
    sensors_by_name: Dict[str, Sensor] = {}
    for sensor_id in sensor_ids:
        sensor: Sensor = Sensor.query.get(sensor_id)
        if not sensor:
            click.echo(f"No sensor with id {sensor_id} known.")
            raise click.Abort
        sensors_by_name[sensor.name] = sensor
    start = isodate.parse_datetime(start_str)  # TODO: make sure it has a tz
    duration = isodate.parse_duration(duration_str)
    # handle belief time
    belief_time_before = None
    if belief_time_before_str:
        belief_time_before = isodate.parse_datetime(belief_time_before_str)
    # query data
    beliefs_by_sensor = TimedBelief.search(
        sensors=list(sensor_ids),
        event_starts_after=start,
        event_ends_before=start + duration,
        beliefs_before=belief_time_before,
        source=source,
        sum_multiple=False,
    )
    # only keep non-empty
    beliefs_by_sensor = {
        sensor_name: beliefs
        for (sensor_name, beliefs) in beliefs_by_sensor.items()
        if not beliefs.empty
    }
    if len(beliefs_by_sensor.keys()) == 0:
        click.echo("No data found!")
        raise click.Abort()
    sensor_names = list(sensors_by_name.keys())
    first_df = beliefs_by_sensor[sensor_names[0]]

    # Build title
    if len(sensor_ids) == 1:
        title = f"Beliefs for Sensor '{sensor_names[0]}' (Id {sensor_ids[0]}).\n"
    else:
        title = f"Beliefs for Sensor(s) [{','.join(sensor_names)}], (Id(s): [{','.join([str(sid) for sid in sensor_ids])}]).\n"
    title += f"Data spans {naturaldelta(duration)} and starts at {start}."
    if belief_time_before:
        title += f"\nOnly beliefs made before: {belief_time_before}."
    if source:
        title += f"\nSource: {source.name}"
    if len(beliefs_by_sensor) == 1:
        title += f"\nThe time resolution (x-axis) is {naturaldelta(first_df.sensor.event_resolution)}."

    uniplot.plot(
        [
            beliefs.event_value
            for beliefs in [beliefs_by_sensor[sn] for sn in sensor_names]
        ],
        title=title,
        color=True,
        lines=True,
        y_unit=first_df.sensor.unit
        if len(beliefs_by_sensor) == 1
        or all(
            sensor.unit == first_df.sensor.unit for sensor in sensors_by_name.values()
        )
        else "",
        legend_labels=sensor_names,
    )


app.cli.add_command(fm_show_data)
