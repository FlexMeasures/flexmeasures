"""
CLI commands for populating the database
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Type
import isodate
import json
import yaml
from pathlib import Path
from io import TextIOBase
from string import Template

from marshmallow import validate
import pandas as pd
import pytz
from flask import current_app as app
from flask.cli import with_appcontext
import click
import getpass
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func, select
from timely_beliefs.sensors.func_store.knowledge_horizons import x_days_ago_at_y_oclock
import timely_beliefs as tb
import timely_beliefs.utils as tb_utils
from workalendar.registry import registry as workalendar_registry

from flexmeasures.cli.utils import (
    DeprecatedDefaultGroup,
    MsgStyle,
    DeprecatedOption,
    DeprecatedOptionsCommand,
)
from flexmeasures.data import db
from flexmeasures.data.scripts.data_gen import (
    add_transmission_zone_asset,
    populate_initial_structure,
    add_default_asset_types,
)
from flexmeasures.data.services.data_sources import get_or_create_source
from flexmeasures.data.services.forecasting import create_forecasting_jobs
from flexmeasures.data.services.scheduling import make_schedule, create_scheduling_job
from flexmeasures.data.services.users import create_user
from flexmeasures.data.models.user import Account, AccountRole, RolesAccounts
from flexmeasures.data.models.time_series import (
    Sensor,
    TimedBelief,
)
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.validation_utils import (
    check_required_attributes,
    MissingAttributeException,
)
from flexmeasures.data.models.annotations import Annotation, get_or_create_annotation
from flexmeasures.data.schemas import (
    AccountIdField,
    AwareDateTimeField,
    DurationField,
    LatitudeField,
    LongitudeField,
    SensorIdField,
    TimeIntervalField,
    VariableQuantityField,
)
from flexmeasures.data.schemas.sources import DataSourceIdField
from flexmeasures.data.schemas.times import TimeIntervalSchema
from flexmeasures.data.schemas.scheduling.storage import EfficiencyField
from flexmeasures.data.schemas.sensors import SensorSchema
from flexmeasures.data.schemas.io import Output
from flexmeasures.data.schemas.units import QuantityField
from flexmeasures.data.schemas.generic_assets import (
    GenericAssetSchema,
    GenericAssetTypeSchema,
)
from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.models.user import User
from flexmeasures.data.services.data_sources import (
    get_source_or_none,
)
from flexmeasures.data.services.utils import get_or_create_model
from flexmeasures.utils import flexmeasures_inflection
from flexmeasures.utils.time_utils import server_now, apply_offset_chain
from flexmeasures.utils.unit_utils import convert_units, ur
from flexmeasures.cli.utils import validate_color_cli, validate_url_cli
from flexmeasures.data.utils import save_to_db
from flexmeasures.data.services.utils import get_asset_or_sensor_ref
from flexmeasures.data.models.reporting import Reporter
from flexmeasures.data.models.reporting.profit import ProfitOrLossReporter
from timely_beliefs import BeliefsDataFrame


@click.group("add")
def fm_add_data():
    """FlexMeasures: Add data."""


@fm_add_data.command("sources")
@click.option(
    "--kind",
    default=["reporter"],
    type=click.Choice(["reporter", "scheduler", "forecaster"]),
    multiple=True,
    help="What kind of data generators to consider in the creation of the basic DataSources. Defaults to `reporter`.",
)
@with_appcontext
def add_sources(kind: list[str]):
    """Create data sources for the data generators found registered in the
    application and the plugins. Currently, this command only registers the
    sources for the Reporters.
    """

    for k in kind:
        # todo: add other data-generators when adapted (and remove this check when all listed under our click.Choice are represented)
        if k not in ("reporter",):
            click.secho(f"Oh no, we don't support kind '{k}' yet.", **MsgStyle.WARN)
            continue
        click.echo(f"Adding `DataSources` for the {k} data generators.")

        for name, data_generator in app.data_generators[k].items():
            ds_info = data_generator.get_data_source_info()

            # add empty data_generator configuration
            ds_info["attributes"] = {"data_generator": {"config": {}, "parameters": {}}}

            source = get_or_create_source(**ds_info)

            click.secho(
                f"Done. DataSource for data generator `{name}` is `{source}`.",
                **MsgStyle.SUCCESS,
            )

    db.session.commit()


@fm_add_data.command("account-role")
@with_appcontext
@click.option("--name", required=True)
@click.option("--description")
def new_account_role(name: str, description: str):
    """
    Create an account role.
    """
    role = db.session.execute(
        select(AccountRole).filter_by(name=name)
    ).scalar_one_or_none()
    if role is not None:
        click.secho(f"Account role '{name}' already exists.", **MsgStyle.ERROR)
        raise click.Abort()
    role = AccountRole(
        name=name,
        description=description,
    )
    db.session.add(role)
    db.session.commit()
    click.secho(
        f"Account role '{name}' (ID: {role.id}) successfully created.",
        **MsgStyle.SUCCESS,
    )


@fm_add_data.command("account")
@with_appcontext
@click.option("--name", required=True)
@click.option("--roles", help="e.g. anonymous,Prosumer,CPO")
@click.option(
    "--primary-color",
    callback=validate_color_cli,
    help="Primary color to use in UI, in hex format. Defaults to FlexMeasures' primary color (#1a3443)",
)
@click.option(
    "--secondary-color",
    callback=validate_color_cli,
    help="Secondary color to use in UI, in hex format. Defaults to FlexMeasures' secondary color (#f1a122)",
)
@click.option(
    "--logo-url",
    callback=validate_url_cli,
    help="Logo URL to use in UI. Defaults to FlexMeasures' logo URL",
)
@click.option(
    "--consultancy",
    "consultancy_account",
    type=AccountIdField(required=False),
    help="ID of the consultancy account, whose consultants will have read access to this account",
)
def new_account(
    name: str,
    roles: str,
    consultancy_account: Account | None,
    primary_color: str | None,
    secondary_color: str | None,
    logo_url: str | None,
):
    """
    Create an account for a tenant in the FlexMeasures platform.
    """
    account = db.session.execute(
        select(Account).filter_by(name=name)
    ).scalar_one_or_none()
    if account is not None:
        click.secho(f"Account '{name}' already exists.", **MsgStyle.ERROR)
        raise click.Abort()

    # make sure both colors or none are given
    if (primary_color and not secondary_color) or (
        not primary_color and secondary_color
    ):
        click.secho(
            "Please provide both primary_color and secondary_color, or leave both fields blank.",
            **MsgStyle.ERROR,
        )
        raise click.Abort()

    # Add '#' if color is given and doesn't already start with it
    primary_color = (
        f"#{primary_color}"
        if primary_color and not primary_color.startswith("#")
        else primary_color
    )
    secondary_color = (
        f"#{secondary_color}"
        if secondary_color and not secondary_color.startswith("#")
        else secondary_color
    )

    account = Account(
        name=name,
        consultancy_account=consultancy_account,
        primary_color=primary_color,
        secondary_color=secondary_color,
        logo_url=logo_url,
    )
    db.session.add(account)
    if roles:
        for role_name in roles.split(","):
            role = db.session.execute(
                select(AccountRole).filter_by(name=role_name)
            ).scalar_one_or_none()
            if role is None:
                click.secho(f"Adding account role {role_name} ...", **MsgStyle.ERROR)
                role = AccountRole(name=role_name)
                db.session.add(role)
            db.session.flush()
            db.session.add(RolesAccounts(role_id=role.id, account_id=account.id))
    db.session.commit()
    click.secho(
        f"Account '{name}' (ID: {account.id}) successfully created.",
        **MsgStyle.SUCCESS,
    )


@fm_add_data.command("user", cls=DeprecatedOptionsCommand)
@with_appcontext
@click.option("--username", required=True)
@click.option("--email", required=True)
@click.option(
    "--account",
    "--account-id",
    "account_id",
    type=int,
    required=True,
    cls=DeprecatedOption,
    deprecated=["--account-id"],
    preferred="--account",
    help="Add user to this account. Follow up with the account's ID.",
)
@click.option("--roles", help="e.g. anonymous,Prosumer,CPO")
@click.option(
    "--timezone",
    "timezone_optional",
    help="Timezone as string, e.g. 'UTC' or 'Europe/Amsterdam' (defaults to FLEXMEASURES_TIMEZONE config setting)",
)
def new_user(
    username: str,
    email: str,
    account_id: int,
    roles: list[str],
    timezone_optional: str | None,
):
    """
    Create a FlexMeasures user.

    The `users create` task from Flask Security Too is too simple for us.
    Use this to add email, timezone and roles.
    """
    if timezone_optional is None:
        timezone = app.config.get("FLEXMEASURES_TIMEZONE", "UTC")
        click.secho(
            f"Setting user timezone to {timezone} (taken from FLEXMEASURES_TIMEZONE config setting)...",
            **MsgStyle.WARN,
        )
    else:
        timezone = timezone_optional
    try:
        pytz.timezone(timezone)
    except pytz.UnknownTimeZoneError:
        click.secho(f"Timezone {timezone} is unknown!", **MsgStyle.ERROR)
        raise click.Abort()
    account = db.session.get(Account, account_id)
    if account is None:
        click.secho(f"No account with ID {account_id} found!", **MsgStyle.ERROR)
        raise click.Abort()
    pwd1 = getpass.getpass(prompt="Please enter the password:")
    pwd2 = getpass.getpass(prompt="Please repeat the password:")
    if pwd1 != pwd2:
        click.secho("Passwords do not match!", **MsgStyle.ERROR)
        raise click.Abort()
    created_user = create_user(
        username=username,
        email=email,
        password=pwd1,
        account_name=account.name,
        timezone=timezone,
        user_roles=roles,
        check_email_deliverability=False,
    )
    db.session.commit()
    click.secho(f"Successfully created user {created_user}", **MsgStyle.SUCCESS)


@fm_add_data.command("sensor", cls=DeprecatedOptionsCommand)
@with_appcontext
@click.option("--name", required=True)
@click.option("--unit", required=True, help="e.g. °C, m/s, kW/m²")
@click.option(
    "--event-resolution",
    required=True,
    type=str,
    help="Expected resolution of the data in ISO8601 duration string",
)
@click.option(
    "--timezone",
    required=True,
    help="Timezone as string, e.g. 'UTC' or 'Europe/Amsterdam'",
)
@click.option(
    "--asset",
    "--asset-id",
    "generic_asset_id",
    required=True,
    type=int,
    cls=DeprecatedOption,
    deprecated=["--asset-id"],
    preferred="--asset",
    help="Generic asset to assign this sensor to",
)
@click.option(
    "--attributes",
    required=False,
    type=str,
    default="{}",
    help='Additional attributes. Passed as JSON string, should be a dict. Hint: Currently, for sensors that measure power, use {"capacity_in_mw": 10} to set a capacity of 10 MW',
)
def add_sensor(**args):
    """Add a sensor."""
    check_timezone(args["timezone"])
    try:
        attributes = json.loads(args["attributes"])
    except json.decoder.JSONDecodeError as jde:
        click.secho(
            f"Error decoding --attributes. Please check your JSON: {jde}",
            **MsgStyle.ERROR,
        )
        raise click.Abort()
    del args["attributes"]  # not part of schema
    if args["event_resolution"].isdigit():
        click.secho(
            "DeprecationWarning: Use ISO8601 duration string for event-resolution, minutes in int will be depricated from v0.16.0",
            **MsgStyle.WARN,
        )
        timedelta_event_resolution = timedelta(minutes=int(args["event_resolution"]))
        isodate_event_resolution = isodate.duration_isoformat(
            timedelta_event_resolution
        )
        args["event_resolution"] = isodate_event_resolution
    check_errors(SensorSchema().validate(args))

    sensor = Sensor(**args)
    if not isinstance(attributes, dict):
        click.secho("Attributes should be a dict.", **MsgStyle.ERROR)
        raise click.Abort()
    sensor.attributes = attributes
    if sensor.measures_power:
        if "capacity_in_mw" not in sensor.attributes:
            click.secho(
                "A sensor which measures power needs a capacity (see --attributes).",
                **MsgStyle.ERROR,
            )
            raise click.Abort()
    db.session.add(sensor)
    db.session.commit()
    click.secho(f"Successfully created sensor with ID {sensor.id}", **MsgStyle.SUCCESS)
    click.secho(
        f"You can access it at its entity address {sensor.entity_address}",
        **MsgStyle.SUCCESS,
    )


@fm_add_data.command("asset-type")
@with_appcontext
@click.option("--name", required=True)
@click.option(
    "--description",
    type=str,
    help="Description (useful to explain acronyms, for example).",
)
def add_asset_type(**kwargs):
    """Add an asset type."""
    check_errors(GenericAssetTypeSchema().validate(kwargs))
    generic_asset_type = GenericAssetType(**kwargs)
    db.session.add(generic_asset_type)
    db.session.commit()
    click.secho(
        f"Successfully created asset type with ID {generic_asset_type.id}.",
        **MsgStyle.SUCCESS,
    )
    click.secho("You can now assign assets to it.", **MsgStyle.SUCCESS)


@fm_add_data.command("asset", cls=DeprecatedOptionsCommand)
@with_appcontext
@click.option("--name", required=True)
@click.option(
    "--latitude",
    type=LatitudeField(),
    help="Latitude of the asset's location",
)
@click.option(
    "--longitude",
    type=LongitudeField(),
    help="Longitude of the asset's location",
)
@click.option(
    "--account",
    "--account-id",
    "account_id",
    type=int,
    required=False,
    cls=DeprecatedOption,
    deprecated=["--account-id"],
    preferred="--account",
    help="Add asset to this account. Follow up with the account's ID. If not set, the asset will become public (which makes it accessible to all users).",
)
@click.option(
    "--asset-type",
    "--asset-type-id",
    "generic_asset_type_id",
    required=True,
    type=int,
    cls=DeprecatedOption,
    deprecated=["--asset-type-id"],
    preferred="--asset-type",
    help="Asset type to assign to this asset",
)
@click.option(
    "--parent-asset",
    "parent_asset_id",
    required=False,
    type=int,
    help="Parent of this asset. The entity needs to exists on the database.",
)
def add_asset(**args):
    """Add an asset."""
    check_errors(GenericAssetSchema().validate(args))
    generic_asset = GenericAsset(**args)
    if generic_asset.account_id is None:
        click.secho(
            "Creating a PUBLIC asset, as no --account-id is given ...",
            **MsgStyle.WARN,
        )
    db.session.add(generic_asset)
    db.session.commit()
    click.secho(
        f"Successfully created asset with ID {generic_asset.id}.", **MsgStyle.SUCCESS
    )
    click.secho("You can now assign sensors to it.", **MsgStyle.SUCCESS)


@fm_add_data.command("initial-structure")
@with_appcontext
def add_initial_structure():
    """Initialize useful structural data."""
    populate_initial_structure(db)


@fm_add_data.command("source")
@with_appcontext
@click.option(
    "--name",
    required=True,
    type=str,
    help="Name of the source (usually an organization)",
)
@click.option(
    "--model",
    required=False,
    type=str,
    help="Optionally, specify a model (for example, a class name, function name or url).",
)
@click.option(
    "--version",
    required=False,
    type=str,
    help="Optionally, specify a version (for example, '1.0'.",
)
@click.option(
    "--type",
    "source_type",
    required=True,
    type=str,
    help="Type of source (for example, 'forecaster' or 'scheduler').",
)
def add_source(name: str, model: str, version: str, source_type: str):
    source = get_or_create_source(
        source=name,
        model=model,
        version=version,
        source_type=source_type,
    )
    db.session.commit()
    click.secho(f"Added source {source.__repr__()}", **MsgStyle.SUCCESS)


@fm_add_data.command("beliefs", cls=DeprecatedOptionsCommand)
@with_appcontext
@click.argument("file", type=click.Path(exists=True))
@click.option(
    "--sensor",
    "--sensor-id",
    "sensor",
    required=True,
    type=SensorIdField(),
    cls=DeprecatedOption,
    deprecated=["--sensor-id"],
    preferred="--sensor",
    help="Record the beliefs under this sensor. Follow up with the sensor's ID. ",
)
@click.option(
    "--source",
    required=True,
    type=str,
    help="Source of the beliefs (an existing source id or name, or a new name).",
)
@click.option(
    "--unit",
    required=False,
    type=str,
    help="Unit of the data, for conversion to the sensor unit, if possible (a string unit such as 'kW' or 'm³/h').\n"
    "Measurements of time itself that are formatted as a 'datetime' or 'timedelta' can be converted to a sensor unit representing time (such as 's' or 'h'),\n"
    "where datetimes are represented as a duration with respect to the UNIX epoch."
    "Hint: to switch the sign of the data, prepend a minus sign.\n"
    "For example, when assigning kW consumption data to a kW production sensor, use '-kW'.",
)
@click.option(
    "--horizon",
    required=False,
    type=int,
    help="Belief horizon in minutes (use positive horizon for ex-ante beliefs or negative horizon for ex-post beliefs).",
)
@click.option(
    "--cp",
    required=False,
    type=click.FloatRange(0, 1),
    help="Cumulative probability in the range [0, 1].",
)
@click.option(
    "--resample/--do-not-resample",
    default=True,
    help="Resample the data to fit the sensor's event resolution. "
    " Only downsampling is currently supported (for example, from hourly to daily data).",
)
@click.option(
    "--allow-overwrite/--do-not-allow-overwrite",
    default=False,
    help="Allow overwriting possibly already existing data.\n"
    "Not allowing overwriting can be much more efficient",
)
@click.option(
    "--skiprows",
    required=False,
    default=1,
    type=int,
    help="Number of rows to skip from the top. Set to >1 to skip additional headers.",
)
@click.option(
    "--na-values",
    required=False,
    multiple=True,
    help="Additional strings to recognize as NaN values. This argument can be given multiple times.",
)
@click.option(
    "--keep-default-na",
    default=False,
    type=bool,
    help="Whether or not to keep NaN values in the data.",
)
@click.option(
    "--nrows",
    required=False,
    type=int,
    help="Number of rows to read (from the top, after possibly skipping rows). Leave out to read all rows.",
)
@click.option(
    "--datecol",
    required=False,
    default=0,
    type=int,
    help="Column number with datetimes (0 is 1st column, the default)",
)
@click.option(
    "--valuecol",
    required=False,
    default=1,
    type=int,
    help="Column number with values (1 is 2nd column, the default)",
)
@click.option(
    "--beliefcol",
    required=False,
    type=int,
    help="Column number with datetimes",
)
@click.option(
    "--timezone",
    required=False,
    default=None,
    help="Timezone as string, e.g. 'UTC' or 'Europe/Amsterdam'",
)
@click.option(
    "--filter-column",
    "filter_columns",
    multiple=True,
    help="Set a column number to filter data. Use together with --filter-value.",
)
@click.option(
    "--filter-value",
    "filter_values",
    multiple=True,
    help="Set a column value to filter data. Only rows with this value will be added. Use together with --filter-column.",
)
@click.option(
    "--delimiter",
    required=True,
    type=str,
    default=",",
    help="[For CSV files] Character to delimit columns per row, defaults to comma",
)
@click.option(
    "--decimal",
    required=False,
    default=".",
    type=str,
    help="[For CSV files] decimal character, e.g. '.' for 10.5",
)
@click.option(
    "--thousands",
    required=False,
    default=None,
    type=str,
    help="[For CSV files] thousands separator, e.g. '.' for 10.035,2",
)
@click.option(
    "--sheet_number",
    required=False,
    type=int,
    help="[For xls or xlsx files] Sheet number with the data (0 is 1st sheet)",
)
def add_beliefs(
    file: str,
    sensor: Sensor,
    source: str,
    filter_columns: list[int],
    filter_values: list[int],
    unit: str | None = None,
    horizon: int | None = None,
    cp: float | None = None,
    resample: bool = True,
    allow_overwrite: bool = False,
    skiprows: int = 1,
    na_values: list[str] | None = None,
    keep_default_na: bool = False,
    nrows: int | None = None,
    datecol: int = 0,
    valuecol: int = 1,
    beliefcol: int | None = None,
    timezone: str | None = None,
    delimiter: str = ",",
    decimal: str = ".",
    thousands: str | None = None,
    sheet_number: int | None = None,
    **kwargs,  # in-code calls to this CLI command can set additional kwargs for use in pandas.read_csv or pandas.read_excel
):
    """Add sensor data from a CSV or Excel file.

    To use default settings, structure your CSV file as follows:

        - One header line (will be ignored!)
        - UTC datetimes in 1st column
        - values in 2nd column

    For example:

        Date,Inflow (cubic meter)
        2020-12-03 14:00,212
        2020-12-03 14:10,215.6
        2020-12-03 14:20,203.8

    In case no --horizon is specified and no beliefcol is specified,
    the moment of executing this CLI command is taken as the time at which the beliefs were recorded.
    """
    _source = parse_source(source)

    # Set up optional parameters for read_csv
    if file.split(".")[-1].lower() == "csv":
        kwargs["infer_datetime_format"] = True
        kwargs["delimiter"] = delimiter
        kwargs["decimal"] = decimal
        kwargs["thousands"] = thousands
    if sheet_number is not None:
        kwargs["sheet_name"] = sheet_number
    if horizon is not None:
        kwargs["belief_horizon"] = timedelta(minutes=horizon)
    elif beliefcol is None:
        kwargs["belief_time"] = server_now().astimezone(pytz.timezone(sensor.timezone))

    # Set up optional filters:
    if len(filter_columns) != len(filter_values):
        raise ValueError(
            "The number of filter columns and filter values should be the same."
        )
    filter_by_column = (
        dict(zip(filter_columns, filter_values)) if filter_columns else None
    )
    bdf = tb.read_csv(
        file,
        sensor,
        source=_source,
        cumulative_probability=cp,
        resample=resample,
        header=None,
        skiprows=skiprows,
        nrows=nrows,
        usecols=(
            [datecol, valuecol] if beliefcol is None else [datecol, beliefcol, valuecol]
        ),
        parse_dates=True,
        na_values=na_values,
        keep_default_na=keep_default_na,
        timezone=timezone,
        filter_by_column=filter_by_column,
        **kwargs,
    )
    duplicate_rows = bdf.index.duplicated(keep="first")
    if any(duplicate_rows) > 0:
        click.secho(
            "Duplicates found. Dropping duplicates for the following records:",
            **MsgStyle.WARN,
        )
        click.secho(bdf[duplicate_rows], **MsgStyle.WARN)
        bdf = bdf[~duplicate_rows]
    if unit is not None:
        bdf["event_value"] = convert_units(
            bdf["event_value"],
            from_unit=unit,
            to_unit=sensor.unit,
            event_resolution=sensor.event_resolution,
        )
    try:
        TimedBelief.add(
            bdf,
            expunge_session=True,
            allow_overwrite=allow_overwrite,
            bulk_save_objects=True,
            commit_transaction=True,
        )
        click.secho(f"Successfully created beliefs\n{bdf}", **MsgStyle.SUCCESS)
    except IntegrityError as e:
        db.session.rollback()
        click.secho(
            f"Failed to create beliefs due to the following error: {e.orig}",
            **MsgStyle.ERROR,
        )
        if not allow_overwrite:
            click.secho(
                "As a possible workaround, use the --allow-overwrite flag.",
                **MsgStyle.ERROR,
            )


@fm_add_data.command("annotation", cls=DeprecatedOptionsCommand)
@with_appcontext
@click.option(
    "--content",
    required=True,
    prompt="Enter annotation",
)
@click.option(
    "--at",
    "start_str",
    required=True,
    help="Annotation is set (or starts) at this datetime. Follow up with a timezone-aware datetime in ISO 6801 format.",
)
@click.option(
    "--until",
    "end_str",
    required=False,
    help="Annotation ends at this datetime. Follow up with a timezone-aware datetime in ISO 6801 format. Defaults to one (nominal) day after the start of the annotation.",
)
@click.option(
    "--account",
    "--account-id",
    "account_ids",
    type=click.INT,
    multiple=True,
    cls=DeprecatedOption,
    deprecated=["--account-id"],
    preferred="--account",
    help="Add annotation to this organisation account. Follow up with the account's ID. This argument can be given multiple times.",
)
@click.option(
    "--asset",
    "--asset-id",
    "generic_asset_ids",
    type=int,
    multiple=True,
    cls=DeprecatedOption,
    deprecated=["--asset-id"],
    preferred="--asset",
    help="Add annotation to this asset. Follow up with the asset's ID. This argument can be given multiple times.",
)
@click.option(
    "--sensor",
    "--sensor-id",
    "sensor_ids",
    type=int,
    multiple=True,
    cls=DeprecatedOption,
    deprecated=["--sensor-id"],
    preferred="--sensor",
    help="Add annotation to this sensor. Follow up with the sensor's ID. This argument can be given multiple times.",
)
@click.option(
    "--user",
    "--user-id",
    "user_id",
    type=int,
    required=True,
    cls=DeprecatedOption,
    deprecated=["--user-id"],
    preferred="--user",
    help="Attribute annotation to this user. Follow up with the user's ID.",
)
def add_annotation(
    content: str,
    start_str: str,
    end_str: str | None,
    account_ids: list[int],
    generic_asset_ids: list[int],
    sensor_ids: list[int],
    user_id: int,
):
    """Add annotation to accounts, assets and/or sensors."""

    # Parse input
    start = pd.Timestamp(start_str)
    end = (
        pd.Timestamp(end_str)
        if end_str is not None
        else start + pd.offsets.DateOffset(days=1)
    )
    accounts = (
        db.session.scalars(select(Account).filter(Account.id.in_(account_ids))).all()
        if account_ids
        else []
    )
    assets = (
        db.session.scalars(
            select(GenericAsset).filter(GenericAsset.id.in_(generic_asset_ids))
        ).all()
        if generic_asset_ids
        else []
    )
    sensors = (
        db.session.scalars(select(Sensor).filter(Sensor.id.in_(sensor_ids))).all()
        if sensor_ids
        else []
    )
    user = db.session.get(User, user_id)
    _source = get_or_create_source(user)

    # Create annotation
    annotation = get_or_create_annotation(
        Annotation(
            content=content,
            start=start,
            end=end,
            source=_source,
            type="label",
        )
    )
    for account in accounts:
        account.annotations.append(annotation)
    for asset in assets:
        asset.annotations.append(annotation)
    for sensor in sensors:
        sensor.annotations.append(annotation)
    db.session.commit()
    click.secho("Successfully added annotation.", **MsgStyle.SUCCESS)


@fm_add_data.command("holidays", cls=DeprecatedOptionsCommand)
@with_appcontext
@click.option(
    "--year",
    type=click.INT,
    help="The year for which to look up holidays",
)
@click.option(
    "--country",
    "countries",
    type=click.STRING,
    multiple=True,
    help="The ISO 3166-1 country/region or ISO 3166-2 sub-region for which to look up holidays (such as US, BR and DE). This argument can be given multiple times.",
)
@click.option(
    "--asset",
    "--asset-id",
    "generic_asset_ids",
    type=click.INT,
    multiple=True,
    cls=DeprecatedOption,
    deprecated=["--asset-id"],
    preferred="--asset",
    help="Add annotations to this asset. Follow up with the asset's ID. This argument can be given multiple times.",
)
@click.option(
    "--account",
    "--account-id",
    "account_ids",
    type=click.INT,
    multiple=True,
    cls=DeprecatedOption,
    deprecated=["--account-id"],
    preferred="--account",
    help="Add annotations to this account. Follow up with the account's ID. This argument can be given multiple times.",
)
def add_holidays(
    year: int,
    countries: list[str],
    generic_asset_ids: list[int],
    account_ids: list[int],
):
    """Add holiday annotations to accounts and/or assets."""
    calendars = workalendar_registry.get_calendars(countries)
    num_holidays = {}

    accounts = (
        db.session.scalars(select(Account).filter(Account.id.in_(account_ids))).all()
        if account_ids
        else []
    )
    assets = (
        db.session.scalars(
            select(GenericAsset).filter(GenericAsset.id.in_(generic_asset_ids))
        ).all()
        if generic_asset_ids
        else []
    )
    annotations = []
    for country, calendar in calendars.items():
        _source = get_or_create_source(
            "workalendar", model=country, source_type="CLI script"
        )
        holidays = calendar().holidays(year)
        for holiday in holidays:
            start = pd.Timestamp(holiday[0])
            end = start + pd.offsets.DateOffset(days=1)
            annotations.append(
                get_or_create_annotation(
                    Annotation(
                        content=holiday[1],
                        start=start,
                        end=end,
                        source=_source,
                        type="holiday",
                    )
                )
            )
        num_holidays[country] = len(holidays)
    db.session.add_all(annotations)
    for account in accounts:
        account.annotations += annotations
    for asset in assets:
        asset.annotations += annotations
    db.session.commit()
    click.secho(
        f"Successfully added holidays to {len(accounts)} {flexmeasures_inflection.pluralize('account', len(accounts))} and {len(assets)} {flexmeasures_inflection.pluralize('asset', len(assets))}:\n{num_holidays}",
        **MsgStyle.SUCCESS,
    )


@fm_add_data.command("forecasts", cls=DeprecatedOptionsCommand)
@with_appcontext
@click.option(
    "--sensor",
    "--sensor-id",
    "sensor_ids",
    multiple=True,
    required=True,
    cls=DeprecatedOption,
    deprecated=["--sensor-id"],
    preferred="--sensor",
    help="Create forecasts for this sensor. Follow up with the sensor's ID. This argument can be given multiple times.",
)
@click.option(
    "--from-date",
    "from_date_str",
    default="2015-02-08",
    help="Forecast from date (inclusive). Follow up with a date in the form yyyy-mm-dd.",
)
@click.option(
    "--to-date",
    "to_date_str",
    default="2015-12-31",
    help="Forecast to date (inclusive). Follow up with a date in the form yyyy-mm-dd.",
)
@click.option(
    "--resolution",
    type=int,
    help="Resolution of forecast in minutes. If not set, resolution is determined from the sensor to be forecasted",
)
@click.option(
    "--horizon",
    "horizons_as_hours",
    multiple=True,
    type=click.Choice(["1", "6", "24", "48"]),
    default=["1", "6", "24", "48"],
    help="Forecasting horizon in hours. This argument can be given multiple times. Defaults to all possible horizons.",
)
@click.option(
    "--as-job",
    is_flag=True,
    help="Whether to queue a forecasting job instead of computing directly. "
    "To process the job, run a worker (on any computer, but configured to the same databases) to process the 'forecasting' queue. Defaults to False.",
)
def create_forecasts(
    sensor_ids: list[int],
    from_date_str: str = "2015-02-08",
    to_date_str: str = "2015-12-31",
    horizons_as_hours: list[str] = ["1"],
    resolution: int | None = None,
    as_job: bool = False,
):
    """
    Create forecasts.

    For example:

        --from-date 2015-02-02 --to-date 2015-02-04 --horizon 6 --sensor 12 --sensor 14

        This will create forecast values from 0am on May 2nd to 0am on May 5th,
        based on a 6-hour horizon, for sensors 12 and 14.

    """
    # make horizons
    horizons = [timedelta(hours=int(h)) for h in horizons_as_hours]

    # apply timezone and set forecast_end to be an inclusive version of to_date
    timezone = app.config.get("FLEXMEASURES_TIMEZONE")
    forecast_start = pd.Timestamp(from_date_str).tz_localize(timezone)
    forecast_end = (pd.Timestamp(to_date_str) + pd.Timedelta("1D")).tz_localize(
        timezone
    )

    event_resolution: timedelta | None
    if resolution is not None:
        event_resolution = timedelta(minutes=resolution)
    else:
        event_resolution = None

    if as_job:
        num_jobs = 0
        for sensor_id in sensor_ids:
            for horizon in horizons:
                # Note that this time period refers to the period of events we are forecasting, while in create_forecasting_jobs
                # the time period refers to the period of belief_times, therefore we are subtracting the horizon.
                jobs = create_forecasting_jobs(
                    sensor_id=sensor_id,
                    horizons=[horizon],
                    start_of_roll=forecast_start - horizon,
                    end_of_roll=forecast_end - horizon,
                )
                num_jobs += len(jobs)
        click.secho(
            f"{num_jobs} new forecasting job(s) added to the queue.",
            **MsgStyle.SUCCESS,
        )
    else:
        from flexmeasures.data.scripts.data_gen import populate_time_series_forecasts

        populate_time_series_forecasts(  # this function reports its own output
            db=app.db,
            sensor_ids=sensor_ids,
            horizons=horizons,
            forecast_start=forecast_start,
            forecast_end=forecast_end,
            event_resolution=event_resolution,
        )


# todo: repurpose `flexmeasures add schedule` (deprecated since v0.12),
#       - see https://github.com/FlexMeasures/flexmeasures/pull/537#discussion_r1048680231
#       - hint for repurposing to invoke custom logic instead of a default subcommand:
#             @fm_add_data.group("schedule", invoke_without_command=True)
#             def create_schedule():
#                 if ctx.invoked_subcommand:
#                     ...
@fm_add_data.group(
    "schedule",
    cls=DeprecatedDefaultGroup,
    default="storage",
    deprecation_message="The command 'flexmeasures add schedule' is deprecated. Please use `flexmeasures add schedule for-storage` instead.",
)
@click.pass_context
@with_appcontext
def create_schedule(ctx):
    """(Deprecated) Create a new schedule for a given power sensor.

    THIS COMMAND HAS BEEN RENAMED TO `flexmeasures add schedule for-storage`
    """
    pass


@create_schedule.command("for-storage", cls=DeprecatedOptionsCommand)
@with_appcontext
@click.option(
    "--sensor",
    "--sensor-id",
    "power_sensor",
    type=SensorIdField(),
    required=True,
    cls=DeprecatedOption,
    deprecated=["--sensor-id"],
    preferred="--sensor",
    help="Create schedule for this sensor. Should be a power sensor. Follow up with the sensor's ID.",
)
@click.option(
    "--consumption-price-sensor",
    "consumption_price_sensor",
    type=SensorIdField(),
    required=False,
    help="Optimize consumption against this sensor. The sensor typically records an electricity price (e.g. in EUR/kWh), but this field can also be used to optimize against some emission intensity factor (e.g. in kg CO₂ eq./kWh). Follow up with the sensor's ID.",
)
@click.option(
    "--production-price-sensor",
    "production_price_sensor",
    type=SensorIdField(),
    required=False,
    help="Optimize production against this sensor. Defaults to the consumption price sensor. The sensor typically records an electricity price (e.g. in EUR/kWh), but this field can also be used to optimize against some emission intensity factor (e.g. in kg CO₂ eq./kWh). Follow up with the sensor's ID.",
)
@click.option(
    "--optimization-context-id",
    "optimization_context_sensor",
    type=SensorIdField(),
    required=False,
    help="To be deprecated. Use consumption-price-sensor instead.",
)
@click.option(
    "--inflexible-device-sensor",
    "inflexible_device_sensors",
    type=SensorIdField(),
    multiple=True,
    help="Take into account the power flow of inflexible devices. Follow up with the sensor's ID."
    " This argument can be given multiple times.",
)
@click.option(
    "--site-power-capacity",
    "site_power_capacity",
    type=VariableQuantityField("MW"),
    required=False,
    default=None,
    help="Site consumption/production power capacity. Provide this as a quantity in power units (e.g. 1 MW or 1000 kW)"
    "or reference a sensor using 'sensor:<id>' (e.g. sensor:34)."
    "It defines both-ways maximum power capacity on the site level.",
)
@click.option(
    "--site-consumption-capacity",
    "site_consumption_capacity",
    type=VariableQuantityField("MW"),
    required=False,
    default=None,
    help="Site consumption power capacity. Provide this as a quantity in power units (e.g. 1 MW or 1000 kW)"
    "or reference a sensor using 'sensor:<id>' (e.g. sensor:34)."
    "It defines the maximum consumption capacity on the site level.",
)
@click.option(
    "--site-production-capacity",
    "site_production_capacity",
    type=VariableQuantityField("MW"),
    required=False,
    default=None,
    help="Site production power capacity. Provide this as a quantity in power units (e.g. 1 MW or 1000 kW)"
    "or reference a sensor using 'sensor:<id>' (e.g. sensor:34)."
    "It defines the maximum production capacity on the site level.",
)
@click.option(
    "--start",
    "start",
    type=AwareDateTimeField(format="iso"),
    required=True,
    help="Schedule starts at this datetime. Follow up with a timezone-aware datetime in ISO 6801 format.",
)
@click.option(
    "--duration",
    "duration",
    type=DurationField(),
    required=True,
    help="Duration of schedule, after --start. Follow up with a duration in ISO 6801 format, e.g. PT1H (1 hour) or PT45M (45 minutes).",
)
@click.option(
    "--soc-at-start",
    "soc_at_start",
    type=QuantityField("%", validate=validate.Range(min=0, max=1)),
    required=True,
    help="State of charge (e.g 32.8%, or 0.328) at the start of the schedule.",
)
@click.option(
    "--soc-target",
    "soc_target_strings",
    type=click.Tuple(
        types=[QuantityField("%", validate=validate.Range(min=0, max=1)), str]
    ),
    multiple=True,
    required=False,
    help="Target state of charge (e.g 100%, or 1) at some datetime. Follow up with a float value and a timezone-aware datetime in ISO 8601 format."
    " This argument can be given multiple times."
    " For example: --soc-target 100% 2022-02-23T13:40:52+00:00",
)
@click.option(
    "--soc-min",
    "soc_min",
    type=QuantityField("%", validate=validate.Range(min=0, max=1)),
    required=False,
    help="Minimum state of charge (e.g 20%, or 0.2) for the schedule.",
)
@click.option(
    "--soc-max",
    "soc_max",
    type=QuantityField("%", validate=validate.Range(min=0, max=1)),
    required=False,
    help="Maximum state of charge (e.g 80%, or 0.8) for the schedule.",
)
@click.option(
    "--roundtrip-efficiency",
    "roundtrip_efficiency",
    type=EfficiencyField(),
    required=False,
    default=1,
    help="Round-trip efficiency (e.g. 85% or 0.85) to use for the schedule. Defaults to 100% (no losses).",
)
@click.option(
    "--charging-efficiency",
    "charging_efficiency",
    type=VariableQuantityField("%"),
    required=False,
    default=None,
    help="Storage charging efficiency to use for the schedule."
    "Provide a quantity with units (e.g. 94%) or a sensor storing the value with the syntax sensor:<id> (e.g. sensor:20)."
    "Defaults to 100% (no losses).",
)
@click.option(
    "--discharging-efficiency",
    "discharging_efficiency",
    type=VariableQuantityField("%"),
    required=False,
    default=None,
    help="Storage discharging efficiency to use for the schedule."
    "Provide a quantity with units (e.g. 94%) or a sensor storing the value with the syntax sensor:<id> (e.g. sensor:20)."
    "Defaults to 100% (no losses).",
)
@click.option(
    "--soc-gain",
    "soc_gain",
    type=VariableQuantityField("MW"),
    required=False,
    default=None,
    help="Specify the State of Charge (SoC) gain as a quantity in power units (e.g. 1 MW or 1000 kW)"
    "or reference a sensor by using 'sensor:<id>' (e.g. sensor:34)."
    "This represents the rate at which storage is charged from a different source.",
)
@click.option(
    "--soc-usage",
    "soc_usage",
    type=VariableQuantityField("MW"),
    required=False,
    default=None,
    help="Specify the State of Charge (SoC) usage as a quantity in power units (e.g. 1 MW or 1000 kW) "
    "or reference a sensor by using 'sensor:<id>' (e.g. sensor:34)."
    "This represents the rate at which the storage is discharged from a different source.",
)
@click.option(
    "--storage-power-capacity",
    "storage_power_capacity",
    type=VariableQuantityField("MW"),
    required=False,
    default=None,
    help="Storage consumption/production power capacity. Provide this as a quantity in power units (e.g. 1 MW or 1000 kW)"
    "or reference a sensor using 'sensor:<id>' (e.g. sensor:34)."
    "It defines both-ways maximum power capacity.",
)
@click.option(
    "--storage-consumption-capacity",
    "storage_consumption_capacity",
    type=VariableQuantityField("MW"),
    required=False,
    default=None,
    help="Storage consumption power capacity. Provide this as a quantity in power units (e.g. 1 MW or 1000 kW)"
    "or reference a sensor using 'sensor:<id>' (e.g. sensor:34)."
    "It defines the storage maximum consumption (charging) capacity.",
)
@click.option(
    "--storage-production-capacity",
    "storage_production_capacity",
    type=VariableQuantityField("MW"),
    required=False,
    default=None,
    help="Storage production power capacity. Provide this as a quantity in power units (e.g. 1 MW or 1000 kW)"
    "or reference a sensor using 'sensor:<id>' (e.g. sensor:34)."
    "It defines the storage maximum production (discharging) capacity.",
)
@click.option(
    "--storage-efficiency",
    "storage_efficiency",
    type=VariableQuantityField("%", default_src_unit="dimensionless"),
    required=False,
    default="100%",
    help="Storage efficiency (e.g. 95% or 0.95) to use for the schedule,"
    " applied over each time step equal to the sensor resolution."
    "This parameter also supports using a reference sensor as 'sensor:<id>' (e.g. sensor:34)."
    " For example, a storage efficiency of 99 percent per (absolute) day, for scheduling a 1-hour resolution sensor, should be passed as a storage efficiency of 0.99**(1/24)."
    " Defaults to 100% (no losses).",
)
@click.option(
    "--as-job",
    is_flag=True,
    help="Whether to queue a scheduling job instead of computing directly. "
    "To process the job, run a worker (on any computer, but configured to the same databases) to process the 'scheduling' queue. Defaults to False.",
)
def add_schedule_for_storage(  # noqa C901
    power_sensor: Sensor,
    consumption_price_sensor: Sensor,
    production_price_sensor: Sensor,
    optimization_context_sensor: Sensor,
    inflexible_device_sensors: list[Sensor],
    site_power_capacity: ur.Quantity | Sensor | None,
    site_consumption_capacity: ur.Quantity | Sensor | None,
    site_production_capacity: ur.Quantity | Sensor | None,
    start: datetime,
    duration: timedelta,
    soc_at_start: ur.Quantity,
    charging_efficiency: ur.Quantity | Sensor | None,
    discharging_efficiency: ur.Quantity | Sensor | None,
    soc_gain: ur.Quantity | Sensor | None,
    soc_usage: ur.Quantity | Sensor | None,
    storage_power_capacity: ur.Quantity | Sensor | None,
    storage_consumption_capacity: ur.Quantity | Sensor | None,
    storage_production_capacity: ur.Quantity | Sensor | None,
    soc_target_strings: list[tuple[ur.Quantity, str]],
    soc_min: ur.Quantity | None = None,
    soc_max: ur.Quantity | None = None,
    roundtrip_efficiency: ur.Quantity | None = None,
    storage_efficiency: ur.Quantity | Sensor | None = None,
    as_job: bool = False,
):
    """Create a new schedule for a storage asset.

    Current limitations:

    - Limited to power sensors (probably possible to generalize to non-electric assets)
    - Only supports datetimes on the hour or a multiple of the sensor resolution thereafter
    """
    # todo: deprecate the 'optimization-context-id' argument in favor of 'consumption-price-sensor' (announced v0.11.0)
    tb_utils.replace_deprecated_argument(
        "optimization-context-id",
        optimization_context_sensor,
        "consumption-price-sensor",
        consumption_price_sensor,
    )

    # Parse input and required sensor attributes
    if not power_sensor.measures_power:
        click.secho(
            f"Sensor with ID {power_sensor.id} is not a power sensor.",
            **MsgStyle.ERROR,
        )
        raise click.Abort()
    if production_price_sensor is None:
        production_price_sensor = consumption_price_sensor
    end = start + duration

    # Convert SoC units (we ask for % in this CLI) to MWh, given the storage capacity
    try:
        check_required_attributes(power_sensor, [("max_soc_in_mwh", float)])
    except MissingAttributeException:
        click.secho(
            f"Sensor {power_sensor} has no max_soc_in_mwh attribute.", **MsgStyle.ERROR
        )
        raise click.Abort()
    capacity_str = f"{power_sensor.get_attribute('max_soc_in_mwh')} MWh"
    soc_at_start = convert_units(soc_at_start.magnitude, soc_at_start.units, "MWh", capacity=capacity_str)  # type: ignore
    soc_targets = []
    for soc_target_tuple in soc_target_strings:
        soc_target_value_str, soc_target_datetime_str = soc_target_tuple
        soc_target_value = convert_units(
            soc_target_value_str.magnitude,
            str(soc_target_value_str.units),
            "MWh",
            capacity=capacity_str,
        )
        soc_targets.append(
            dict(value=soc_target_value, datetime=soc_target_datetime_str)
        )

    if soc_min is not None:
        soc_min = convert_units(soc_min.magnitude, str(soc_min.units), "MWh", capacity=capacity_str)  # type: ignore
    if soc_max is not None:
        soc_max = convert_units(soc_max.magnitude, str(soc_max.units), "MWh", capacity=capacity_str)  # type: ignore
    if roundtrip_efficiency is not None:
        roundtrip_efficiency = roundtrip_efficiency.magnitude / 100.0

    scheduling_kwargs = dict(
        start=start,
        end=end,
        belief_time=server_now(),
        resolution=power_sensor.event_resolution,
        flex_model={
            "soc-at-start": soc_at_start,
            "soc-targets": soc_targets,
            "soc-min": soc_min,
            "soc-max": soc_max,
            "soc-unit": "MWh",
            "roundtrip-efficiency": roundtrip_efficiency,
        },
        flex_context={
            "consumption-price-sensor": consumption_price_sensor.id,
            "production-price-sensor": production_price_sensor.id,
            "inflexible-device-sensors": [s.id for s in inflexible_device_sensors],
        },
    )

    quantity_or_sensor_vars = {
        "flex_model": {
            "charging-efficiency": charging_efficiency,
            "discharging-efficiency": discharging_efficiency,
            "storage-efficiency": storage_efficiency,
            "soc-gain": soc_gain,
            "soc-usage": soc_usage,
            "power-capacity": storage_power_capacity,
            "consumption-capacity": storage_consumption_capacity,
            "production-capacity": storage_production_capacity,
        },
        "flex_context": {
            "site-power-capacity": site_power_capacity,
            "site-consumption-capacity": site_consumption_capacity,
            "site-production-capacity": site_production_capacity,
        },
    }

    for key in ["flex_model", "flex_context"]:
        for field_name, value in quantity_or_sensor_vars[key].items():
            if value is not None:
                if "efficiency" in field_name:
                    unit = "%"
                else:
                    unit = "MW"

                scheduling_kwargs[key][field_name] = VariableQuantityField(
                    unit
                )._serialize(value, None, None)

    if as_job:
        job = create_scheduling_job(asset_or_sensor=power_sensor, **scheduling_kwargs)
        if job:
            click.secho(
                f"New scheduling job {job.id} has been added to the queue.",
                **MsgStyle.SUCCESS,
            )
    else:
        success = make_schedule(
            asset_or_sensor=get_asset_or_sensor_ref(power_sensor),
            **scheduling_kwargs,
        )
        if success:
            click.secho("New schedule is stored.", **MsgStyle.SUCCESS)


@create_schedule.command("for-process", cls=DeprecatedOptionsCommand)
@with_appcontext
@click.option(
    "--sensor",
    "--sensor-id",
    "power_sensor",
    type=SensorIdField(),
    required=True,
    cls=DeprecatedOption,
    deprecated=["--sensor-id"],
    preferred="--sensor",
    help="Create schedule for this sensor. Should be a power sensor. Follow up with the sensor's ID.",
)
@click.option(
    "--consumption-price-sensor",
    "consumption_price_sensor",
    type=SensorIdField(),
    required=False,
    help="Optimize consumption against this sensor. The sensor typically records an electricity price (e.g. in EUR/kWh), but this field can also be used to optimize against some emission intensity factor (e.g. in kg CO₂ eq./kWh). Follow up with the sensor's ID.",
)
@click.option(
    "--start",
    "start",
    type=AwareDateTimeField(format="iso"),
    required=True,
    help="Schedule starts at this datetime. Follow up with a timezone-aware datetime in ISO 6801 format.",
)
@click.option(
    "--duration",
    "duration",
    type=DurationField(),
    required=True,
    help="Duration of schedule, after --start. Follow up with a duration in ISO 6801 format, e.g. PT1H (1 hour) or PT45M (45 minutes).",
)
@click.option(
    "--process-duration",
    "process_duration",
    type=DurationField(),
    required=True,
    help="Duration of the process. Follow up with a duration in ISO 6801 format, e.g. PT1H (1 hour) or PT45M (45 minutes).",
)
@click.option(
    "--process-type",
    "process_type",
    type=click.Choice(["INFLEXIBLE", "BREAKABLE", "SHIFTABLE"], case_sensitive=False),
    required=False,
    default="SHIFTABLE",
    help="Process schedule policy: INFLEXIBLE, BREAKABLE or SHIFTABLE.",
)
@click.option(
    "--process-power",
    "process_power",
    type=ur.Quantity,
    required=True,
    help="Constant power of the process during the activation period, e.g. 4kW.",
)
@click.option(
    "--forbid",
    type=TimeIntervalField(),
    multiple=True,
    required=False,
    help="Add time restrictions to the optimization, where the load will not be scheduled into."
    'Use the following format to define the restrictions: `{"start":<timezone-aware datetime in ISO 6801>, "duration":<ISO 6801 duration>}`'
    "This options allows to define multiple time restrictions by using the --forbid for different periods.",
)
@click.option(
    "--as-job",
    is_flag=True,
    help="Whether to queue a scheduling job instead of computing directly. "
    "To process the job, run a worker (on any computer, but configured to the same databases) to process the 'scheduling' queue. Defaults to False.",
)
def add_schedule_process(
    power_sensor: Sensor,
    consumption_price_sensor: Sensor,
    start: datetime,
    duration: timedelta,
    process_duration: timedelta,
    process_type: str,
    process_power: ur.Quantity,
    forbid: list | None = None,
    as_job: bool = False,
):
    """Create a new schedule for a process asset.

    Current limitations:
    - Only supports consumption blocks.
    - Not taking into account grid constraints or other processes.
    """

    if forbid is None:
        forbid = []

    # Parse input and required sensor attributes
    if not power_sensor.measures_power:
        click.secho(
            f"Sensor with ID {power_sensor.id} is not a power sensor.",
            **MsgStyle.ERROR,
        )
        raise click.Abort()

    end = start + duration

    process_power = convert_units(process_power.magnitude, process_power.units, "MW")  # type: ignore

    scheduling_kwargs = dict(
        start=start,
        end=end,
        belief_time=server_now(),
        resolution=power_sensor.event_resolution,
        flex_model={
            "duration": pd.Timedelta(process_duration).isoformat(),
            "process-type": process_type,
            "power": process_power,
            "time-restrictions": [TimeIntervalSchema().dump(f) for f in forbid],
        },
    )

    if consumption_price_sensor is not None:
        scheduling_kwargs["flex_context"] = {
            "consumption-price-sensor": consumption_price_sensor.id,
        }

    if as_job:
        job = create_scheduling_job(asset_or_sensor=power_sensor, **scheduling_kwargs)
        if job:
            click.secho(
                f"New scheduling job {job.id} has been added to the queue.",
                **MsgStyle.SUCCESS,
            )
    else:
        success = make_schedule(
            asset_or_sensor=get_asset_or_sensor_ref(power_sensor),
            **scheduling_kwargs,
        )
        if success:
            click.secho("New schedule is stored.", **MsgStyle.SUCCESS)


@fm_add_data.command("report")
@with_appcontext
@click.option(
    "--config",
    "config_file",
    required=False,
    type=click.File("r"),
    help="Path to the JSON or YAML file with the configuration of the reporter.",
)
@click.option(
    "--source",
    "source",
    required=False,
    type=DataSourceIdField(),
    help="DataSource ID of the `Reporter`.",
)
@click.option(
    "--parameters",
    "parameters_file",
    required=False,
    type=click.File("r"),
    help="Path to the JSON or YAML file with the report parameters (passed to the compute step).",
)
@click.option(
    "--reporter",
    "reporter_class",
    default="PandasReporter",
    type=click.STRING,
    help="Reporter class registered in flexmeasures.data.models.reporting or in an available flexmeasures plugin."
    " Use the command `flexmeasures show reporters` to list all the available reporters.",
)
@click.option(
    "--start",
    "start",
    type=AwareDateTimeField(format="iso"),
    required=False,
    help="Report start time. `--start-offset` can be used instead. Follow up with a timezone-aware datetime in ISO 6801 format.",
)
@click.option(
    "--start-offset",
    "start_offset",
    type=str,
    required=False,
    help="Report start offset time from now. Use multiple Pandas offset strings separated by commas, e.g: -3D,DB,1W. Use DB or HB to offset to the begin of the day or hour, respectively.",
)
@click.option(
    "--end-offset",
    "end_offset",
    type=str,
    required=False,
    help="Report end offset time from now. Use multiple Pandas offset strings separated by commas, e.g: -3D,DB,1W. Use DB or HB to offset to the begin of the day or hour, respectively.",
)
@click.option(
    "--end",
    "end",
    type=AwareDateTimeField(format="iso"),
    required=False,
    help="Report end time. `--end-offset` can be used instead. Follow up with a timezone-aware datetime in ISO 6801 format.",
)
@click.option(
    "--resolution",
    "resolution",
    type=DurationField(format="iso"),
    required=False,
    help="Time resolution of the input time series to employ for the calculations. Follow up with a ISO 8601 duration string",
)
@click.option(
    "--output-file",
    "output_file_pattern",
    required=False,
    type=click.Path(),
    help="Format of the output file. Use dollar sign ($) to interpolate values among the following ones:"
    " now (current time), name (name of the output), sensor_id (id of the sensor), column (column of the output)."
    " Example: 'result_file_$name_$now.csv'. "
    "Use the `.csv` suffix to save the results as Comma Separated Values and `.xlsx` to export them as Excel sheets.",
)
@click.option(
    "--timezone",
    "timezone",
    required=False,
    help="Timezone as string, e.g. 'UTC' or 'Europe/Amsterdam' (defaults to the timezone of the sensor used to save the report)."
    "The timezone of the first output sensor (specified in the parameters) is taken as a default.",
)
@click.option(
    "--dry-run",
    "dry_run",
    is_flag=True,
    help="Add this flag to avoid saving the results to the database.",
)
@click.option(
    "--edit-config",
    "edit_config",
    is_flag=True,
    help="Add this flag to edit the configuration of the Reporter in your default text editor (e.g. nano).",
)
@click.option(
    "--edit-parameters",
    "edit_parameters",
    is_flag=True,
    help="Add this flag to edit the parameters passed to the Reporter in your default text editor (e.g. nano).",
)
@click.option(
    "--save-config",
    "save_config",
    is_flag=True,
    help="Add this flag to save the `config` in the attributes of the DataSource for future reference.",
)
def add_report(  # noqa: C901
    reporter_class: str,
    source: DataSource | None = None,
    config_file: TextIOBase | None = None,
    parameters_file: TextIOBase | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    start_offset: str | None = None,
    end_offset: str | None = None,
    resolution: timedelta | None = None,
    output_file_pattern: Path | None = None,
    dry_run: bool = False,
    edit_config: bool = False,
    edit_parameters: bool = False,
    save_config: bool = False,
    timezone: str | None = None,
):
    """
    Create a new report using the Reporter class and save the results
    to the database or export them as CSV or Excel file.
    """

    config = dict()

    if config_file:
        config = yaml.safe_load(config_file)

    if edit_config:
        config = launch_editor("/tmp/config.yml")

    parameters = dict()

    if parameters_file:
        parameters = yaml.safe_load(parameters_file)

    if edit_parameters:
        parameters = launch_editor("/tmp/parameters.yml")

    # check if sensor is not provided in the `parameters` description
    if "output" not in parameters or len(parameters["output"]) == 0:
        click.secho(
            "At least one output sensor needs to be specified in the parameters description.",
            **MsgStyle.ERROR,
        )
        raise click.Abort()

    output = [Output().load(o) for o in parameters["output"]]

    # compute now in the timezone local to the output sensor
    if timezone is not None:
        check_timezone(timezone)

    now = pytz.timezone(
        zone=timezone if timezone is not None else output[0]["sensor"].timezone
    ).localize(datetime.now())

    # apply offsets, if provided
    if start_offset is not None:
        if start is None:
            start = now
        start = apply_offset_chain(start, start_offset)

    if end_offset is not None:
        if end is None:
            end = now
        end = apply_offset_chain(end, end_offset)

    # the case of not getting --start or --start-offset
    if start is None:
        click.secho(
            "Either --start or --start-offset should be provided."
            " Trying to use the latest datapoint of the report sensor as the start time...",
            **MsgStyle.WARN,
        )

        # todo: get the oldest last_value among all the sensors
        last_value_datetime = db.session.execute(
            select(func.max(TimedBelief.event_start))
            .select_from(TimedBelief)
            .filter_by(sensor_id=output[0]["sensor"].id)
        ).scalar_one_or_none()
        # If there's data saved to the reporter sensors
        if last_value_datetime is not None:
            start = last_value_datetime
        else:
            click.secho(
                "Could not find any data for the output sensors provided. Such data is needed to compute"
                " a sensible default start for the report, so setting a start explicitly would resolve this issue.",
                **MsgStyle.ERROR,
            )
            raise click.Abort()

    # the case of not getting --end or --end-offset
    if end is None:
        click.secho(
            "Either --end or --end-offset should be provided."
            " Trying to use the current time as the end...",
            **MsgStyle.WARN,
        )
        end = now

    click.echo(f"Report scope:\n\tstart: {start}\n\tend:   {end}")

    if source is None:
        click.echo(
            f"Looking for the Reporter {reporter_class} among all the registered reporters...",
        )

        # get reporter class
        ReporterClass: Type[Reporter] = app.data_generators.get("reporter").get(
            reporter_class
        )

        # check if it exists
        if ReporterClass is None:
            click.secho(
                f"Reporter class `{reporter_class}` not available.",
                **MsgStyle.ERROR,
            )
            raise click.Abort()

        click.secho(f"Reporter {reporter_class} found.", **MsgStyle.SUCCESS)

        # initialize reporter class with the reporter sensor and reporter config
        reporter: Reporter = ReporterClass(config=config, save_config=save_config)

    else:
        try:
            reporter: Reporter = source.data_generator  # type: ignore

            if not isinstance(reporter, Reporter):
                raise NotImplementedError(
                    f"DataGenerator `{reporter}` is not of the type `Reporter`"
                )

            click.secho(
                f"Reporter `{reporter.__class__.__name__}` fetched successfully from the database.",
                **MsgStyle.SUCCESS,
            )

        except NotImplementedError:
            click.secho(
                f"Error! DataSource `{source}` not storing a valid Reporter.",
                **MsgStyle.ERROR,
            )

        reporter._save_config = save_config

    if ("start" not in parameters) and (start is not None):
        parameters["start"] = start.isoformat()
    if ("end" not in parameters) and (end is not None):
        parameters["end"] = end.isoformat()
    if ("resolution" not in parameters) and (resolution is not None):
        parameters["resolution"] = pd.Timedelta(resolution).isoformat()

    click.echo("Report computation is running...")

    # compute the report
    results: BeliefsDataFrame = reporter.compute(parameters=parameters)

    for result in results:
        data = result["data"]
        sensor = result["sensor"]
        if not data.empty:
            click.secho(
                f"Report computation done for sensor `{sensor}`.", **MsgStyle.SUCCESS
            )
        else:
            click.secho(
                f"Report computation done for sensor `{sensor}`, but the report is empty.",
                **MsgStyle.WARN,
            )

        # save the report if it's not running in dry mode
        if not dry_run:
            click.echo(f"Saving report for sensor `{sensor}` to the database...")
            save_to_db(data.dropna())
            db.session.commit()
            click.secho(
                f"Success. The report for sensor `{sensor}` has been saved to the database.",
                **MsgStyle.SUCCESS,
            )
        else:
            click.echo(
                f"Not saving report for sensor `{sensor}` to the database  (because of --dry-run), but this is what I computed:\n{data}"
            )

        # if an output file path is provided, save the data
        if output_file_pattern:
            suffix = (
                str(output_file_pattern).split(".")[-1]
                if "." in str(output_file_pattern)
                else ""
            )
            template = Template(str(output_file_pattern))

            filename = template.safe_substitute(
                sensor_id=result["sensor"].id,
                name=result.get("name", ""),
                column=result.get("column", ""),
                reporter_class=reporter_class,
                now=now.strftime("%Y_%m_%dT%H%M%S"),
            )

            if suffix == "xlsx":  # save to EXCEL
                data.to_excel(filename)
                click.secho(
                    f"Success. The report for sensor `{sensor}` has been exported as EXCEL to the file `{filename}`",
                    **MsgStyle.SUCCESS,
                )

            elif suffix == "csv":  # save to CSV
                data.to_csv(filename)
                click.secho(
                    f"Success. The report for sensor `{sensor}` has been exported as CSV to the file `{filename}`",
                    **MsgStyle.SUCCESS,
                )

            else:  # default output format: CSV.
                click.secho(
                    f"File suffix not provided. Exporting results for sensor `{sensor}` as CSV to file {filename}",
                    **MsgStyle.WARN,
                )
                data.to_csv(filename)
        else:
            click.secho(
                "Success.",
                **MsgStyle.SUCCESS,
            )


def launch_editor(filename: str) -> dict:
    """Launch editor to create/edit a json object"""
    click.edit("{\n}", filename=filename)

    with open(filename, "r") as f:
        content = yaml.safe_load(f)
        if content is None:
            return dict()

        return content


@fm_add_data.command("toy-account")
@with_appcontext
@click.option(
    "--kind",
    default="battery",
    type=click.Choice(["battery", "process", "reporter"]),
    help="What kind of toy account. Defaults to a battery.",
)
@click.option("--name", type=str, default="Toy Account", help="Name of the account")
def add_toy_account(kind: str, name: str):
    """
    Create a toy account, for tutorials and trying things.
    """
    asset_types = add_default_asset_types(db=db)
    location = (52.374, 4.88969)  # Amsterdam

    # make an account (if not exist)
    account = db.session.execute(
        select(Account).filter_by(name=name)
    ).scalar_one_or_none()
    if account:
        click.secho(
            f"Account '{account}' already exists. Skipping account creation. Use `flexmeasures delete account --id {account.id}` if you need to remove it.",
            **MsgStyle.WARN,
        )

    # make an account user (account-admin?)
    email = "toy-user@flexmeasures.io"
    user = db.session.execute(select(User).filter_by(email=email)).scalar_one_or_none()
    if user is not None:
        click.secho(
            f"User with email {email} already exists in account {user.account.name}.",
            **MsgStyle.WARN,
        )
    else:
        user = create_user(
            email=email,
            check_email_deliverability=False,
            password="toy-password",
            user_roles=["account-admin"],
            account_name=name,
        )
        click.secho(
            f"Toy account {name} with user {user.email} created successfully. You might want to run `flexmeasures show account --id {user.account.id}`",
            **MsgStyle.SUCCESS,
        )

    db.session.commit()

    # add public day-ahead market (as sensor of transmission zone asset)
    nl_zone = add_transmission_zone_asset("NL", db=db)
    day_ahead_sensor = get_or_create_model(
        Sensor,
        name="day-ahead prices",
        generic_asset=nl_zone,
        unit="EUR/MWh",
        timezone="Europe/Amsterdam",
        event_resolution=timedelta(minutes=60),
        knowledge_horizon=(
            x_days_ago_at_y_oclock,
            {"x": 1, "y": 12, "z": "Europe/Paris"},
        ),
    )
    db.session.commit()
    click.secho(
        f"The sensor recording day-ahead prices is {day_ahead_sensor} (ID: {day_ahead_sensor.id}).",
        **MsgStyle.SUCCESS,
    )

    account_id = user.account_id

    def create_asset_with_one_sensor(
        asset_name: str,
        asset_type: str,
        sensor_name: str,
        unit: str = "MW",
        parent_asset_id: int | None = None,
        **asset_attributes,
    ):
        asset_kwargs = dict()
        if parent_asset_id is not None:
            asset_kwargs["parent_asset_id"] = parent_asset_id

        asset = get_or_create_model(
            GenericAsset,
            name=asset_name,
            generic_asset_type=asset_types[asset_type],
            owner=db.session.get(Account, account_id),
            latitude=location[0],
            longitude=location[1],
            **asset_kwargs,
        )
        if len(asset_attributes) > 0:
            asset.attributes = asset_attributes

        sensor_specs = dict(
            generic_asset=asset,
            unit=unit,
            timezone="Europe/Amsterdam",
            event_resolution=timedelta(minutes=15),
        )
        sensor = get_or_create_model(
            Sensor,
            name=sensor_name,
            **sensor_specs,
        )
        return sensor

    # create building asset
    building_asset = get_or_create_model(
        GenericAsset,
        name="toy-building",
        generic_asset_type=asset_types["building"],
        owner=db.session.get(Account, account_id),
        latitude=location[0],
        longitude=location[1],
    )
    db.session.flush()

    if kind == "battery":
        # create battery
        discharging_sensor = create_asset_with_one_sensor(
            "toy-battery",
            "battery",
            "discharging",
            parent_asset_id=building_asset.id,
            capacity_in_mw=0.5,
            min_soc_in_mwh=0.05,
            max_soc_in_mwh=0.45,
        )

        # create solar
        production_sensor = create_asset_with_one_sensor(
            "toy-solar", "solar", "production", parent_asset_id=building_asset.id
        )

        # add day-ahead price sensor and PV production sensor to show on the battery's asset page
        db.session.flush()
        battery = discharging_sensor.generic_asset
        battery.attributes["sensors_to_show"] = [
            day_ahead_sensor.id,
            [
                production_sensor.id,
                discharging_sensor.id,
            ],
        ]

        db.session.commit()

        click.secho(
            f"The sensor recording battery discharging is {discharging_sensor} (ID: {discharging_sensor.id}).",
            **MsgStyle.SUCCESS,
        )
        click.secho(
            f"The sensor recording solar forecasts is {production_sensor} (ID: {production_sensor.id}).",
            **MsgStyle.SUCCESS,
        )
    elif kind == "process":
        inflexible_power = create_asset_with_one_sensor(
            "toy-process",
            "process",
            "Power (Inflexible)",
        )

        breakable_power = create_asset_with_one_sensor(
            "toy-process",
            "process",
            "Power (Breakable)",
        )

        shiftable_power = create_asset_with_one_sensor(
            "toy-process",
            "process",
            "Power (Shiftable)",
        )

        db.session.flush()

        process = shiftable_power.generic_asset
        process.attributes["sensors_to_show"] = [
            day_ahead_sensor.id,
            inflexible_power.id,
            breakable_power.id,
            shiftable_power.id,
        ]

        db.session.commit()

        click.secho(
            f"The sensor recording the power of the inflexible load is {inflexible_power} (ID: {inflexible_power.id}).",
            **MsgStyle.SUCCESS,
        )
        click.secho(
            f"The sensor recording the power of the breakable load is {breakable_power} (ID: {breakable_power.id}).",
            **MsgStyle.SUCCESS,
        )
        click.secho(
            f"The sensor recording the power of the shiftable load is {shiftable_power} (ID: {shiftable_power.id}).",
            **MsgStyle.SUCCESS,
        )
    elif kind == "reporter":
        # Part A) of tutorial IV
        grid_connection_capacity = get_or_create_model(
            Sensor,
            name="grid connection capacity",
            generic_asset=building_asset,
            timezone="Europe/Amsterdam",
            event_resolution="P1Y",
            unit="MW",
        )
        db.session.commit()

        click.secho(
            f"The sensor storing the grid connection capacity of the building is {grid_connection_capacity} (ID: {grid_connection_capacity.id}).",
            **MsgStyle.SUCCESS,
        )

        tz = pytz.timezone(app.config.get("FLEXMEASURES_TIMEZONE", "Europe/Amsterdam"))
        current_year = datetime.now().year
        start_year = datetime(current_year, 1, 1)

        belief = TimedBelief(
            event_start=tz.localize(start_year),
            belief_time=tz.localize(datetime.now()),
            event_value=0.5,
            source=db.session.get(DataSource, 1),
            sensor=grid_connection_capacity,
        )

        db.session.add(belief)
        db.session.commit()

        headroom = create_asset_with_one_sensor(
            "toy-battery", "battery", "headroom", parent_asset_id=building_asset.id
        )

        db.session.commit()

        click.secho(
            f"The sensor storing the headroom is {headroom} (ID: {headroom.id}).",
            **MsgStyle.SUCCESS,
        )

        for name in ["Inflexible", "Breakable", "Shiftable"]:
            loss_sensor = create_asset_with_one_sensor(
                "toy-process", "process", f"costs ({name})", unit="EUR"
            )

            db.session.commit()
            click.secho(
                f"The sensor storing the loss is {loss_sensor} (ID: {loss_sensor.id}).",
                **MsgStyle.SUCCESS,
            )

        reporter = ProfitOrLossReporter(
            consumption_price_sensor=day_ahead_sensor, loss_is_positive=True
        )
        ds = reporter.data_source
        db.session.commit()

        click.secho(
            f"Reporter `ProfitOrLossReporter` saved with the day ahead price sensor in the `DataSource` (id={ds.id})",
            **MsgStyle.SUCCESS,
        )


app.cli.add_command(fm_add_data)


def check_timezone(timezone):
    try:
        pytz.timezone(timezone)
    except pytz.UnknownTimeZoneError:
        click.secho("Timezone %s is unknown!" % timezone, **MsgStyle.ERROR)
        raise click.Abort()


def check_errors(errors: dict[str, list[str]]):
    if errors:
        click.secho(
            f"Please correct the following errors:\n{errors}.\n Use the --help flag to learn more.",
            **MsgStyle.ERROR,
        )
        raise click.Abort()


def parse_source(source):
    if source.isdigit():
        _source = get_source_or_none(int(source))
        if not _source:
            click.secho(f"Failed to find source {source}.", **MsgStyle.ERROR)
            raise click.Abort()
    else:
        _source = get_or_create_source(source, source_type="CLI script")
    return _source
