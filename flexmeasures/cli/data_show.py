"""
CLI commands for listing database contents and classes
"""

from __future__ import annotations

from datetime import datetime, timedelta

import click
from flask import current_app as app
from flask.cli import with_appcontext
from tabulate import tabulate
from humanize import naturaldelta, naturaltime
import pandas as pd
import uniplot
import vl_convert as vlc
from string import Template
import pytz
import json

from flexmeasures.data.models.user import Account, AccountRole, User, Role
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.data.schemas.generic_assets import GenericAssetIdField
from flexmeasures.data.schemas.sensors import SensorIdField
from flexmeasures.data.schemas.account import AccountIdField
from flexmeasures.data.schemas.sources import DataSourceIdField
from flexmeasures.data.schemas.times import AwareDateTimeField, DurationField
from flexmeasures.data.services.time_series import simplify_index
from flexmeasures.utils.time_utils import determine_minimum_resampling_resolution
from flexmeasures.cli.utils import MsgStyle
from flexmeasures.utils.coding_utils import delete_key_recursive


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
        click.secho("No accounts created yet.", **MsgStyle.WARN)
        raise click.Abort()
    click.echo("All accounts on this FlexMeasures instance:\n ")
    account_data = [
        (
            account.id,
            account.name,
            GenericAsset.query.filter(GenericAsset.account_id == account.id).count(),
        )
        for account in accounts
    ]
    click.echo(tabulate(account_data, headers=["ID", "Name", "Assets"]))


@fm_show_data.command("roles")
@with_appcontext
def list_roles():
    """
    Show available account and user roles
    """
    account_roles = AccountRole.query.order_by(AccountRole.name).all()
    if not account_roles:
        click.secho("No account roles created yet.", **MsgStyle.WARN)
        raise click.Abort()
    click.echo("Account roles:\n")
    click.echo(
        tabulate(
            [(r.id, r.name, r.description) for r in account_roles],
            headers=["ID", "Name", "Description"],
        )
    )
    click.echo()
    user_roles = Role.query.order_by(Role.name).all()
    if not user_roles:
        click.secho("No user roles created yet, not even admin.", **MsgStyle.WARN)
        raise click.Abort()
    click.echo("User roles:\n")
    click.echo(
        tabulate(
            [(r.id, r.name, r.description) for r in user_roles],
            headers=["ID", "Name", "Description"],
        )
    )


@fm_show_data.command("account")
@with_appcontext
@click.option("--id", "account", type=AccountIdField(), required=True)
def show_account(account):
    """
    Show information about an account, including users and assets.
    """
    click.echo(f"========{len(account.name) * '='}========")
    click.echo(f"Account {account.name} (ID: {account.id})")
    click.echo(f"========{len(account.name) * '='}========\n")

    if account.account_roles:
        click.echo(
            f"Account role(s): {','.join([role.name for role in account.account_roles])}"
        )
    else:
        click.secho("Account has no roles.", **MsgStyle.WARN)
    click.echo()

    users = User.query.filter_by(account_id=account.id).order_by(User.username).all()
    if not users:
        click.secho("No users in account ...", **MsgStyle.WARN)
    else:
        click.echo("All users:\n ")
        user_data = [
            (
                user.id,
                user.username,
                user.email,
                naturaltime(user.last_login_at),
                naturaltime(user.last_seen_at),
                ",".join([role.name for role in user.roles]),
            )
            for user in users
        ]
        click.echo(
            tabulate(
                user_data,
                headers=["ID", "Name", "Email", "Last Login", "Last Seen", "Roles"],
            )
        )

    click.echo()
    assets = (
        GenericAsset.query.filter_by(account_id=account.id)
        .order_by(GenericAsset.name)
        .all()
    )
    if not assets:
        click.secho("No assets in account ...", **MsgStyle.WARN)
    else:
        click.echo("All assets:\n ")
        asset_data = [
            (asset.id, asset.name, asset.generic_asset_type.name, asset.location)
            for asset in assets
        ]
        click.echo(tabulate(asset_data, headers=["ID", "Name", "Type", "Location"]))


@fm_show_data.command("asset-types")
@with_appcontext
def list_asset_types():
    """
    Show available asset types
    """
    asset_types = GenericAssetType.query.order_by(GenericAssetType.name).all()
    if not asset_types:
        click.secho("No asset types created yet.", **MsgStyle.WARN)
        raise click.Abort()
    click.echo(
        tabulate(
            [(t.id, t.name, t.description) for t in asset_types],
            headers=["ID", "Name", "Description"],
        )
    )


@fm_show_data.command("asset")
@with_appcontext
@click.option("--id", "asset", type=GenericAssetIdField(), required=True)
def show_generic_asset(asset):
    """
    Show asset info and list sensors
    """
    click.echo(f"======{len(asset.name) * '='}========")
    click.echo(f"Asset {asset.name} (ID: {asset.id})")
    click.echo(f"======{len(asset.name) * '='}========\n")

    asset_data = [
        (
            asset.generic_asset_type.name,
            asset.location,
            "".join([f"{k}: {v}\n" for k, v in asset.attributes.items()]),
        )
    ]
    click.echo(tabulate(asset_data, headers=["Type", "Location", "Attributes"]))

    click.echo()
    sensors = (
        Sensor.query.filter_by(generic_asset_id=asset.id).order_by(Sensor.name).all()
    )
    if not sensors:
        click.secho("No sensors in asset ...", **MsgStyle.WARN)
        raise click.Abort()

    click.echo("All sensors in asset:\n ")
    sensor_data = [
        (
            sensor.id,
            sensor.name,
            sensor.unit,
            naturaldelta(sensor.event_resolution),
            sensor.timezone,
            "".join([f"{k}: {v}\n" for k, v in sensor.attributes.items()]),
        )
        for sensor in sensors
    ]
    click.echo(
        tabulate(
            sensor_data,
            headers=["ID", "Name", "Unit", "Resolution", "Timezone", "Attributes"],
        )
    )


@fm_show_data.command("data-sources")
@with_appcontext
@click.option(
    "--id",
    "source",
    required=False,
    type=DataSourceIdField(),
    help="ID of data source.",
)
@click.option(
    "--show-attributes",
    "show_attributes",
    type=bool,
    help="Whether to show the attributes of the DataSource.",
    is_flag=True,
)
def list_data_sources(source: DataSource | None = None, show_attributes: bool = False):
    """
    Show available data sources
    """
    if source is None:
        sources = (
            DataSource.query.order_by(DataSource.type)
            .order_by(DataSource.name)
            .order_by(DataSource.model)
            .order_by(DataSource.version)
            .all()
        )
    else:
        sources = [source]

    if not sources:
        click.secho("No data sources created yet.", **MsgStyle.WARN)
        raise click.Abort()

    headers = ["ID", "Name", "User ID", "Model", "Version"]

    if show_attributes:
        headers.append("Attributes")

    rows = dict()

    for source in sources:
        row = [
            source.id,
            source.name,
            source.user_id,
            source.model,
            source.version,
        ]
        if show_attributes:
            row.append(json.dumps(source.attributes, indent=4))

        if source.type not in rows:
            rows[source.type] = [row]
        else:
            rows[source.type].append(row)

    for ds_type, row in rows.items():
        click.echo(f"type: {ds_type}")
        click.echo("=" * len(ds_type))
        click.echo(tabulate(row, headers=headers))
        click.echo("\n")


@fm_show_data.command("chart")
@with_appcontext
@click.option(
    "--sensor",
    "sensors",
    required=False,
    multiple=True,
    type=SensorIdField(),
    help="ID of sensor(s). This argument can be given multiple times.",
)
@click.option(
    "--asset",
    "assets",
    required=False,
    multiple=True,
    type=GenericAssetIdField(),
    help="ID of asset(s). This argument can be given multiple times.",
)
@click.option(
    "--start",
    "start",
    type=AwareDateTimeField(),
    required=True,
    help="Plot starting at this datetime. Follow up with a timezone-aware datetime in ISO 6801 format.",
)
@click.option(
    "--end",
    "end",
    type=AwareDateTimeField(),
    required=True,
    help="Plot ending at this datetime. Follow up with a timezone-aware datetime in ISO 6801 format.",
)
@click.option(
    "--belief-time",
    "belief_time",
    type=AwareDateTimeField(),
    required=False,
    help="Time at which beliefs had been known. Follow up with a timezone-aware datetime in ISO 6801 format.",
)
@click.option(
    "--height",
    "height",
    required=False,
    type=int,
    default=200,
    help="Height of the image in pixels..",
)
@click.option(
    "--width",
    "width",
    required=False,
    type=int,
    default=500,
    help="Width of the image in pixels.",
)
@click.option(
    "--filename",
    "filename_template",
    required=False,
    type=str,
    default="chart-$now.png",
    help="Format of the output file. Use dollar sign ($) to interpolate values among the following ones:"
    " now (current time), id (id of the sensor or asset), entity_type (either 'asset' or 'sensor')"
    " Example: 'result_file_$entity_type_$id_$now.csv' -> 'result_file_asset_1_2023-08-24T14:47:08' ",
)
def chart(
    sensors: list[Sensor] | None = None,
    assets: list[GenericAsset] | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    belief_time: datetime | None = None,
    height: int | None = None,
    width: int | None = None,
    filename_template: str | None = None,
):
    """
    Export sensor or asset charts in PNG or SVG formats. For example:

        flexmeasures show chart --start 2023-08-15T00:00:00+02:00 --end 2023-08-16T00:00:00+02:00 --asset 1 --sensor 3
    """

    datetime_format = "%Y-%m-%dT%H:%M:%S"

    if sensors is None and assets is None:
        click.secho(
            "No sensor or asset IDs provided. Please, try passing them using the options `--asset` or `--sensor`.",
            **MsgStyle.ERROR,
        )
        raise click.Abort()

    if sensors is None:
        sensors = []
    if assets is None:
        assets = []

    for entity in sensors + assets:

        entity_type = "sensor"

        if isinstance(entity, GenericAsset):
            entity_type = "asset"

        timezone = app.config["FLEXMEASURES_TIMEZONE"]
        now = pytz.timezone(zone=timezone).localize(datetime.now())

        belief_time_str = ""

        if belief_time is not None:
            belief_time_str = belief_time.strftime(datetime_format)

        template = Template(str(filename_template))
        filename = template.safe_substitute(
            id=entity.id,
            entity_type=entity_type,
            now=now.strftime(datetime_format),
            start=start.strftime(datetime_format),
            end=end.strftime(datetime_format),
            belief_time=belief_time_str,
        )
        click.echo(f"Generating a chart for `{entity}`...")

        # need to fetch the entities as they get detached
        # and we get the (in)famous detached instance error.
        if entity_type == "asset":
            entity = GenericAsset.query.get(entity.id)
        else:
            entity = Sensor.query.get(entity.id)

        chart_description = entity.chart(
            event_starts_after=start,
            event_ends_before=end,
            beliefs_before=belief_time,
            include_data=True,
        )

        # remove formatType as it relies on a custom JavaScript function
        chart_description = delete_key_recursive(chart_description, "formatType")

        # set width and height
        chart_description["width"] = width
        chart_description["height"] = height

        png_data = vlc.vegalite_to_png(vl_spec=chart_description, scale=2)

        with open(filename, "wb") as f:
            f.write(png_data)

        click.secho(
            f"Chart for `{entity}` has been saved successfully as `{filename}`.",
            **MsgStyle.SUCCESS,
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
@click.option(
    "--resolution",
    "resolution",
    type=DurationField(),
    required=False,
    help="Resolution of the data. If not set, defaults to the minimum resolution of the sensor data.",
)
@click.option(
    "--timezone",
    "timezone",
    type=str,
    required=False,
    help="Timezone of the data. If not set, defaults to the timezone of the first non-empty sensor.",
)
@click.option(
    "--to-file",
    "filepath",
    required=False,
    type=str,
    help="Set a filepath to store the beliefs as a CSV file.",
)
def plot_beliefs(
    sensors: list[Sensor],
    start: datetime,
    duration: timedelta,
    resolution: timedelta | None,
    timezone: str | None,
    belief_time_before: datetime | None,
    source: DataSource | None,
    filepath: str | None,
):
    """
    Show a simple plot of belief data directly in the terminal, and optionally, save the data to a CSV file.
    """
    sensors = list(sensors)
    if resolution is None:
        resolution = determine_minimum_resampling_resolution(
            [sensor.event_resolution for sensor in sensors]
        )

    # query data
    beliefs_by_sensor = TimedBelief.search(
        sensors=sensors,
        event_starts_after=start,
        event_ends_before=start + duration,
        beliefs_before=belief_time_before,
        source=source,
        one_deterministic_belief_per_event=True,
        resolution=resolution,
        sum_multiple=False,
    )
    # only keep non-empty
    empty_sensors = []
    for s in sensors:
        if beliefs_by_sensor[s.name].empty:
            click.secho(
                f"No data found for sensor '{s.name}' (ID: {s.id})", **MsgStyle.WARN
            )
            beliefs_by_sensor.pop(s.name)
            empty_sensors.append(s)
    for s in empty_sensors:
        sensors.remove(s)
    if len(beliefs_by_sensor.keys()) == 0:
        click.secho("No data found!", **MsgStyle.WARN)
        raise click.Abort()
    if all(sensor.unit == sensors[0].unit for sensor in sensors):
        shared_unit = sensors[0].unit
    else:
        shared_unit = ""
        click.secho(
            "The y-axis shows no unit, because the selected sensors do not share the same unit.",
            **MsgStyle.WARN,
        )
    df = pd.concat([simplify_index(df) for df in beliefs_by_sensor.values()], axis=1)
    df.columns = beliefs_by_sensor.keys()

    # Convert to the requested or default timezone
    if timezone is not None:
        timezone = sensors[0].timezone
    df.index = df.index.tz_convert(timezone)

    # Build title
    if len(sensors) == 1:
        title = f"Beliefs for Sensor '{sensors[0].name}' (ID {sensors[0].id}).\n"
    else:
        title = f"Beliefs for Sensor(s) [{', '.join([s.name for s in sensors])}], (ID(s): [{', '.join([str(s.id) for s in sensors])}]).\n"
    title += f"Data spans {naturaldelta(duration)} and starts at {start}."
    if belief_time_before:
        title += f"\nOnly beliefs made before: {belief_time_before}."
    if source:
        title += f"\nSource: {source.description}"
    title += f"\nThe time resolution (x-axis) is {naturaldelta(resolution)}."

    uniplot.plot(
        [df[col] for col in df.columns],
        title=title,
        color=True,
        lines=True,
        y_unit=shared_unit,
        legend_labels=[s.name for s in sensors]
        if shared_unit
        else [s.name + f" (in {s.unit})" for s in sensors],
    )
    if filepath is not None:
        df.columns = pd.MultiIndex.from_arrays(
            [df.columns, [df.sensor.unit for df in beliefs_by_sensor.values()]]
        )
        df.to_csv(filepath)
        click.secho("Data saved to file.", **MsgStyle.SUCCESS)


def list_items(item_type):
    """
    Show available items of a specific type.
    """

    click.echo(f"{item_type.capitalize()}:\n")
    click.echo(
        tabulate(
            [
                (
                    item_name,
                    item_class.__version__,
                    item_class.__author__,
                    item_class.__module__,
                )
                for item_name, item_class in getattr(app, item_type).items()
            ],
            headers=["name", "version", "author", "module"],
        )
    )


@fm_show_data.command("reporters")
@with_appcontext
def list_reporters():
    """
    Show available reporters.
    """

    with app.app_context():
        list_items("reporters")


@fm_show_data.command("schedulers")
@with_appcontext
def list_schedulers():
    """
    Show available schedulers.
    """

    with app.app_context():
        list_items("schedulers")


app.cli.add_command(fm_show_data)
