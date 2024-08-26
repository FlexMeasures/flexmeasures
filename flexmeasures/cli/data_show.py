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
from sqlalchemy import select, func

from flexmeasures.data import db
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
from flexmeasures.cli.utils import MsgStyle, validate_unique
from flexmeasures.utils.coding_utils import delete_key_recursive
from flexmeasures.utils.flexmeasures_inflection import join_words_into_a_list
from flexmeasures.cli.utils import (
    DeprecatedOptionsCommand,
    DeprecatedOption,
    get_sensor_aliases,
)


@click.group("show")
def fm_show_data():
    """FlexMeasures: Show data."""


@fm_show_data.command("accounts")
@with_appcontext
def list_accounts():
    """
    List all accounts on this FlexMeasures instance.
    """
    accounts = db.session.scalars(select(Account).order_by(Account.name)).all()
    if not accounts:
        click.secho("No accounts created yet.", **MsgStyle.WARN)
        raise click.Abort()
    click.echo("All accounts on this FlexMeasures instance:\n ")
    account_data = [
        (
            account.id,
            account.name,
            db.session.scalar(
                select(func.count())
                .select_from(GenericAsset)
                .filter_by(account_id=account.id)
            ),
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
    account_roles = db.session.scalars(
        select(AccountRole).order_by(AccountRole.name)
    ).all()
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
    user_roles = db.session.scalars(select(Role).order_by(Role.name)).all()
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

    users = db.session.scalars(
        select(User).filter_by(account_id=account.id).order_by(User.username)
    ).all()
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
    assets = db.session.scalars(
        select(GenericAsset)
        .filter_by(account_id=account.id)
        .order_by(GenericAsset.name)
    ).all()
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
    asset_types = db.session.scalars(
        select(GenericAssetType).order_by(GenericAssetType.name)
    ).all()
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
    separator_num = 18 if asset.parent_asset is not None else 8
    click.echo(f"======{len(asset.name) * '='}{separator_num * '='}")
    click.echo(f"Asset {asset.name} (ID: {asset.id})")
    if asset.parent_asset is not None:
        click.echo(
            f"Child of asset {asset.parent_asset.name} (ID: {asset.parent_asset.id})"
        )
    click.echo(f"======{len(asset.name) * '='}{separator_num * '='}\n")

    asset_data = [
        (
            asset.generic_asset_type.name,
            asset.location,
            "".join([f"{k}: {v}\n" for k, v in asset.attributes.items()]),
        )
    ]
    click.echo(tabulate(asset_data, headers=["Type", "Location", "Attributes"]))

    child_asset_data = [
        (
            child.id,
            child.name,
            child.generic_asset_type.name,
        )
        for child in asset.child_assets
    ]
    click.echo()
    click.echo(f"======{len(asset.name) * '='}===================")
    click.echo(f"Child assets of {asset.name} (ID: {asset.id})")
    click.echo(f"======{len(asset.name) * '='}===================\n")
    if child_asset_data:
        click.echo(tabulate(child_asset_data, headers=["Id", "Name", "Type"]))
    else:
        click.secho("No children assets ...", **MsgStyle.WARN)

    click.echo()
    sensors = db.session.scalars(
        select(Sensor).filter_by(generic_asset_id=asset.id).order_by(Sensor.name)
    ).all()
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
        sources = db.session.scalars(
            select(DataSource)
            .order_by(DataSource.type)
            .order_by(DataSource.name)
            .order_by(DataSource.model)
            .order_by(DataSource.version)
        ).all()
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
@click.option(
    "--resolution",
    "resolution",
    type=DurationField(),
    required=False,
    help="Resolution of the data in ISO 8601 format. If not set, defaults to the minimum resolution of the sensor data. Note: Nominal durations like 'P1D' are converted to absolute timedeltas.",
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
    resolution: timedelta | None = None,
):
    """
    Export sensor or asset charts in PNG or SVG formats. For example:

        flexmeasures show chart --start 2023-08-15T00:00:00+02:00 --end 2023-08-16T00:00:00+02:00 --asset 1 --sensor 3 --resolution P1D
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
            entity = db.session.get(GenericAsset, entity.id)
        else:
            entity = db.session.get(Sensor, entity.id)

        chart_description = entity.chart(
            event_starts_after=start,
            event_ends_before=end,
            beliefs_before=belief_time,
            include_data=True,
            resolution=resolution,
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


@fm_show_data.command("beliefs", cls=DeprecatedOptionsCommand)
@with_appcontext
@click.option(
    "--sensor",
    "--sensor-id",
    "sensors",
    required=True,
    multiple=True,
    callback=validate_unique,
    type=SensorIdField(),
    cls=DeprecatedOption,
    preferred="--sensor",
    deprecated=["--sensor-id"],
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
    "--source",
    "--source-id",
    "source",
    required=False,
    type=DataSourceIdField(),
    cls=DeprecatedOption,
    preferred="--source",
    deprecated=["--source-id"],
    help="Source of the beliefs (an existing source id).",
)
@click.option(
    "--source-type",
    "source_types",
    required=False,
    type=str,
    help="Only show beliefs from this type of source, for example, 'user', 'forecaster' or 'scheduler'.",
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
@click.option(
    "--include-ids/--exclude-ids",
    "include_ids",
    default=False,
    type=bool,
    help="Include sensor IDs in the plot's legend labels and the file's column headers. "
    "NB non-unique sensor names will always show an ID.",
)
@click.option(
    "--reduced-paths/--full-paths",
    "reduce_paths",
    default=True,
    type=bool,
    help="Whether to include the full path to the asset that the sensor belongs to"
    "which shows any parent assets and their account, "
    "or a reduced version of the path, which shows as much detail as is needed to distinguish the sensors.",
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
    source_types: list[str] = None,
    include_ids: bool = False,
    reduce_paths: bool = True,
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
        source_types=source_types,
        one_deterministic_belief_per_event=True,
        resolution=resolution,
        sum_multiple=False,
    )

    # Only keep non-empty (and abort in case of no data)
    for s in sensors:
        if beliefs_by_sensor[s].empty:
            click.secho(f"No data found for sensor {s.id} ({s.name})", **MsgStyle.WARN)
            beliefs_by_sensor.pop(s)
    if len(beliefs_by_sensor) == 0:
        click.secho("No data found!", **MsgStyle.WARN)
        raise click.Abort()
    sensors = list(beliefs_by_sensor.keys())

    # Concatenate data
    df = pd.concat([simplify_index(df) for df in beliefs_by_sensor.values()], axis=1)

    # Find out whether the Y-axis should show a shared unit
    if all(sensor.unit == sensors[0].unit for sensor in sensors):
        shared_unit = sensors[0].unit
    else:
        shared_unit = ""
        click.secho(
            "The y-axis shows no unit, because the selected sensors do not share the same unit.",
            **MsgStyle.WARN,
        )

    # Decide whether to include sensor IDs
    if include_ids:
        df.columns = [f"{s.name} (ID {s.id})" for s in sensors]
    else:
        # In case of non-unique sensor names, show more of the sensor's ancestry
        duplicates = find_duplicates(sensors, "name")
        if duplicates:
            message = "The following sensor name"
            message += "s are " if len(duplicates) > 1 else " is "
            message += (
                f"duplicated: {join_words_into_a_list(duplicates)}. "
                f"To distinguish the sensors, their plot labels will include more parent assets and their account, as needed. "
                f"To show the full path for each sensor, use the --full-path flag. "
                f"Or to uniquely label them by their ID instead, use the --include-ids flag."
            )
            click.secho(message, **MsgStyle.WARN)
        sensor_aliases = get_sensor_aliases(sensors, reduce_paths=reduce_paths)
        df.columns = [sensor_aliases.get(s.id, s.name) for s in sensors]

    # Convert to the requested or default timezone
    if timezone is not None:
        timezone = sensors[0].timezone
    df.index = df.index.tz_convert(timezone)

    # Build title
    if len(sensors) == 1:
        title = f"Beliefs for Sensor '{sensors[0].name}' (ID {sensors[0].id}).\n"
    else:
        title = f"Beliefs for Sensors {join_words_into_a_list([s.name + ' (ID ' + str(s.id) + ')' for s in sensors])}.\n"
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
        legend_labels=df.columns
        if shared_unit
        else [f"{col} in {s.unit}" for col in df.columns],
    )
    if filepath is not None:
        df.columns = pd.MultiIndex.from_arrays(
            [df.columns, [df.sensor.unit for df in beliefs_by_sensor.values()]]
        )
        df.to_csv(filepath)
        click.secho("Data saved to file.", **MsgStyle.SUCCESS)


def find_duplicates(_list: list, attr: str | None = None) -> list:
    """Find duplicates in a list, optionally based on a specified attribute.

    :param _list:   The input list to search for duplicates.
    :param attr:    The attribute name to consider when identifying duplicates.
                    If None, the function will check for duplicates based on the elements themselves.
    :returns:       A list containing the duplicate elements found in the input list.
    """
    if attr:
        _list = [getattr(item, attr) for item in _list]
    return [item for item in set(_list) if _list.count(item) > 1]


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
