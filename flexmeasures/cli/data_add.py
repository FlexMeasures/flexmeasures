"""CLI Tasks for populating the database - most useful in development"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import json

from marshmallow import validate
import numpy as np
import pandas as pd
import pytz
from flask import current_app as app
from flask.cli import with_appcontext
import click
import getpass
from sqlalchemy.exc import IntegrityError
from timely_beliefs.sensors.func_store.knowledge_horizons import x_days_ago_at_y_oclock
import timely_beliefs as tb
from workalendar.registry import registry as workalendar_registry

from flexmeasures.data import db
from flexmeasures.data.scripts.data_gen import (
    add_transmission_zone_asset,
    populate_initial_structure,
    add_default_asset_types,
)
from flexmeasures.data.services.forecasting import create_forecasting_jobs
from flexmeasures.data.services.scheduling import make_schedule
from flexmeasures.data.services.users import create_user
from flexmeasures.data.models.user import Account, AccountRole, RolesAccounts
from flexmeasures.data.models.time_series import (
    Sensor,
    TimedBelief,
)
from flexmeasures.data.models.validation_utils import (
    check_required_attributes,
    MissingAttributeException,
)
from flexmeasures.data.models.annotations import Annotation, get_or_create_annotation
from flexmeasures.data.schemas import AwareDateTimeField, DurationField, SensorIdField
from flexmeasures.data.schemas.sensors import SensorSchema
from flexmeasures.data.schemas.units import QuantityField
from flexmeasures.data.schemas.generic_assets import (
    GenericAssetSchema,
    GenericAssetTypeSchema,
)
from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.models.user import User
from flexmeasures.data.queries.data_sources import (
    get_or_create_source,
    get_source_or_none,
)
from flexmeasures.utils import flexmeasures_inflection
from flexmeasures.utils.time_utils import server_now
from flexmeasures.utils.unit_utils import convert_units, ur


@click.group("add")
def fm_add_data():
    """FlexMeasures: Add data."""


@fm_add_data.command("account-role")
@with_appcontext
@click.option("--name", required=True)
@click.option("--description")
def new_account_role(name: str, description: str):
    """
    Create an account role.
    """
    role = AccountRole.query.filter_by(name=name).one_or_none()
    if role is not None:
        click.echo(f"Account role '{name}' already exists.")
        raise click.Abort
    role = AccountRole(name=name, description=description)
    db.session.add(role)
    db.session.commit()
    print(f"Account role '{name}' (ID: {role.id}) successfully created.")


@fm_add_data.command("account")
@with_appcontext
@click.option("--name", required=True)
@click.option("--roles", help="e.g. anonymous,Prosumer,CPO")
def new_account(name: str, roles: str):
    """
    Create an account for a tenant in the FlexMeasures platform.
    """
    account = db.session.query(Account).filter_by(name=name).one_or_none()
    if account is not None:
        click.echo(f"Account '{name}' already exists.")
        raise click.Abort
    account = Account(name=name)
    db.session.add(account)
    if roles:
        for role_name in roles.split(","):
            role = AccountRole.query.filter_by(name=role_name).one_or_none()
            if role is None:
                print(f"Adding account role {role_name} ...")
                role = AccountRole(name=role_name)
                db.session.add(role)
            db.session.flush()
            db.session.add(RolesAccounts(role_id=role.id, account_id=account.id))
    db.session.commit()
    print(f"Account '{name}' (ID: {account.id}) successfully created.")


@fm_add_data.command("user")
@with_appcontext
@click.option("--username", required=True)
@click.option("--email", required=True)
@click.option("--account-id", type=int, required=True)
@click.option("--roles", help="e.g. anonymous,Prosumer,CPO")
@click.option(
    "--timezone",
    "timezone_optional",
    help="timezone as string, e.g. 'UTC' or 'Europe/Amsterdam' (defaults to FLEXMEASURES_TIMEZONE config setting)",
)
def new_user(
    username: str,
    email: str,
    account_id: int,
    roles: List[str],
    timezone_optional: Optional[str],
):
    """
    Create a FlexMeasures user.

    The `users create` task from Flask Security Too is too simple for us.
    Use this to add email, timezone and roles.
    """
    if timezone_optional is None:
        timezone = app.config.get("FLEXMEASURES_TIMEZONE", "UTC")
        print(
            f"Setting user timezone to {timezone} (taken from FLEXMEASURES_TIMEZONE config setting)..."
        )
    else:
        timezone = timezone_optional
    try:
        pytz.timezone(timezone)
    except pytz.UnknownTimeZoneError:
        print(f"Timezone {timezone} is unknown!")
        raise click.Abort
    account = db.session.query(Account).get(account_id)
    if account is None:
        print(f"No account with ID {account_id} found!")
        raise click.Abort
    pwd1 = getpass.getpass(prompt="Please enter the password:")
    pwd2 = getpass.getpass(prompt="Please repeat the password:")
    if pwd1 != pwd2:
        print("Passwords do not match!")
        raise click.Abort
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
    print(f"Successfully created user {created_user}")


@fm_add_data.command("sensor")
@with_appcontext
@click.option("--name", required=True)
@click.option("--unit", required=True, help="e.g. °C, m/s, kW/m²")
@click.option(
    "--event-resolution",
    required=True,
    type=int,
    help="Expected resolution of the data in minutes",
)
@click.option(
    "--timezone",
    required=True,
    help="timezone as string, e.g. 'UTC' or 'Europe/Amsterdam'",
)
@click.option(
    "--asset-id",
    "generic_asset_id",
    required=True,
    type=int,
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
        print(f"Error decoding --attributes. Please check your JSON: {jde}")
        raise click.Abort()
    del args["attributes"]  # not part of schema
    check_errors(SensorSchema().validate(args))
    args["event_resolution"] = timedelta(minutes=args["event_resolution"])
    sensor = Sensor(**args)
    if not isinstance(attributes, dict):
        print("Attributes should be a dict.")
        raise click.Abort()
    sensor.attributes = attributes
    if sensor.measures_power:
        if "capacity_in_mw" not in sensor.attributes:
            print("A sensor which measures power needs a capacity (see --attributes).")
            raise click.Abort
    db.session.add(sensor)
    db.session.commit()
    print(f"Successfully created sensor with ID {sensor.id}")
    print(f"You can access it at its entity address {sensor.entity_address}")


@fm_add_data.command("asset-type")
@with_appcontext
@click.option("--name", required=True)
@click.option(
    "--description",
    type=str,
    help="Description (useful to explain acronyms, for example).",
)
def add_asset_type(**args):
    """Add an asset type."""
    check_errors(GenericAssetTypeSchema().validate(args))
    generic_asset_type = GenericAssetType(**args)
    db.session.add(generic_asset_type)
    db.session.commit()
    print(f"Successfully created asset type with ID {generic_asset_type.id}.")
    print("You can now assign assets to it.")


@fm_add_data.command("asset")
@with_appcontext
@click.option("--name", required=True)
@click.option(
    "--latitude",
    type=float,
    help="Latitude of the asset's location",
)
@click.option(
    "--longitude",
    type=float,
    help="Longitude of the asset's location",
)
@click.option("--account-id", type=int, required=True)
@click.option(
    "--asset-type-id",
    "generic_asset_type_id",
    required=True,
    type=int,
    help="Asset type to assign to this asset",
)
def add_asset(**args):
    """Add an asset."""
    check_errors(GenericAssetSchema().validate(args))
    generic_asset = GenericAsset(**args)
    db.session.add(generic_asset)
    db.session.commit()
    print(f"Successfully created asset with ID {generic_asset.id}.")
    print("You can now assign sensors to it.")


@fm_add_data.command("initial-structure")
@with_appcontext
def add_initial_structure():
    """Initialize useful structural data."""
    populate_initial_structure(db)


@fm_add_data.command("beliefs")
@with_appcontext
@click.argument("file", type=click.Path(exists=True))
@click.option(
    "--sensor-id",
    required=True,
    type=click.IntRange(min=1),
    help="Sensor to which the beliefs pertain.",
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
    "--delimiter",
    required=True,
    type=str,
    default=",",
    help="[For csv files] Character to delimit columns per row, defaults to comma",
)
@click.option(
    "--decimal",
    required=False,
    default=".",
    type=str,
    help="[For csv files] decimal character, e.g. '.' for 10.5",
)
@click.option(
    "--thousands",
    required=False,
    default=None,
    type=str,
    help="[For csv files] thousands separator, e.g. '.' for 10.035,2",
)
@click.option(
    "--sheet_number",
    required=False,
    type=int,
    help="[For xls or xlsx files] Sheet number with the data (0 is 1st sheet)",
)
def add_beliefs(
    file: str,
    sensor_id: int,
    source: str,
    unit: Optional[str] = None,
    horizon: Optional[int] = None,
    cp: Optional[float] = None,
    resample: bool = True,
    allow_overwrite: bool = False,
    skiprows: int = 1,
    na_values: List[str] = None,
    nrows: Optional[int] = None,
    datecol: int = 0,
    valuecol: int = 1,
    delimiter: str = ",",
    decimal: str = ".",
    thousands: Optional[str] = None,
    sheet_number: Optional[int] = None,
    **kwargs,  # in-code calls to this CLI command can set additional kwargs for use in pandas.read_csv or pandas.read_excel
):
    """Add sensor data from a csv file (also accepts xls or xlsx).

    To use default settings, structure your csv file as follows:

        - One header line (will be ignored!)
        - UTC datetimes in 1st column
        - values in 2nd column

    For example:

        Date,Inflow (cubic meter)
        2020-12-03 14:00,212
        2020-12-03 14:10,215.6
        2020-12-03 14:20,203.8

    In case no --horizon is specified, the moment of executing this CLI command is taken
    as the time at which the beliefs were recorded.
    """
    sensor = Sensor.query.filter(Sensor.id == sensor_id).one_or_none()
    if sensor is None:
        print(f"Failed to create beliefs: no sensor found with ID {sensor_id}.")
        return
    if source.isdigit():
        _source = get_source_or_none(int(source), source_type="CLI script")
        if not _source:
            print(f"Failed to find source {source}.")
            return
    else:
        _source = get_or_create_source(source, source_type="CLI script")

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
    else:
        kwargs["belief_time"] = server_now().astimezone(pytz.timezone(sensor.timezone))

    bdf = tb.read_csv(
        file,
        sensor,
        source=_source,
        cumulative_probability=cp,
        resample=resample,
        header=None,
        skiprows=skiprows,
        nrows=nrows,
        usecols=[datecol, valuecol],
        parse_dates=True,
        na_values=na_values,
        **kwargs,
    )
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
        print(f"Successfully created beliefs\n{bdf}")
    except IntegrityError as e:
        db.session.rollback()
        print(f"Failed to create beliefs due to the following error: {e.orig}")
        if not allow_overwrite:
            print("As a possible workaround, use the --allow-overwrite flag.")


@fm_add_data.command("annotation")
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
    "--account-id",
    "account_ids",
    type=click.INT,
    multiple=True,
    help="Add annotation to this organisation account. Follow up with the account's ID. This argument can be given multiple times.",
)
@click.option(
    "--asset-id",
    "generic_asset_ids",
    type=int,
    multiple=True,
    help="Add annotation to this asset. Follow up with the asset's ID. This argument can be given multiple times.",
)
@click.option(
    "--sensor-id",
    "sensor_ids",
    type=int,
    multiple=True,
    help="Add annotation to this sensor. Follow up with the sensor's ID. This argument can be given multiple times.",
)
@click.option(
    "--user-id",
    type=int,
    required=True,
    help="Attribute annotation to this user. Follow up with the user's ID.",
)
def add_annotation(
    content: str,
    start_str: str,
    end_str: Optional[str],
    account_ids: List[int],
    generic_asset_ids: List[int],
    sensor_ids: List[int],
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
        db.session.query(Account).filter(Account.id.in_(account_ids)).all()
        if account_ids
        else []
    )
    assets = (
        db.session.query(GenericAsset)
        .filter(GenericAsset.id.in_(generic_asset_ids))
        .all()
        if generic_asset_ids
        else []
    )
    sensors = (
        db.session.query(Sensor).filter(Sensor.id.in_(sensor_ids)).all()
        if sensor_ids
        else []
    )
    user = db.session.query(User).get(user_id)
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
    print("Successfully added annotation.")


@fm_add_data.command("holidays")
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
    "--asset-id",
    "generic_asset_ids",
    type=click.INT,
    multiple=True,
    help="Add annotations to this asset. Follow up with the asset's ID. This argument can be given multiple times.",
)
@click.option(
    "--account-id",
    "account_ids",
    type=click.INT,
    multiple=True,
    help="Add annotations to this account. Follow up with the account's ID. This argument can be given multiple times.",
)
def add_holidays(
    year: int,
    countries: List[str],
    generic_asset_ids: List[int],
    account_ids: List[int],
):
    """Add holiday annotations to accounts and/or assets."""
    calendars = workalendar_registry.get_calendars(countries)
    num_holidays = {}

    accounts = (
        db.session.query(Account).filter(Account.id.in_(account_ids)).all()
        if account_ids
        else []
    )
    assets = (
        db.session.query(GenericAsset)
        .filter(GenericAsset.id.in_(generic_asset_ids))
        .all()
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
    print(
        f"Successfully added holidays to {len(accounts)} {flexmeasures_inflection.pluralize('account', len(accounts))} and {len(assets)} {flexmeasures_inflection.pluralize('asset', len(assets))}:\n{num_holidays}"
    )


@fm_add_data.command("forecasts")
@with_appcontext
@click.option(
    "--sensor-id",
    "sensor_ids",
    multiple=True,
    required=True,
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
    help="Whether to queue a forecasting job instead of computing directly."
    " Useful to run locally and create forecasts on a remote server. In that case, just point the redis db in your"
    " config settings to that of the remote server. To process the job, run a worker to process the forecasting queue. Defaults to False.",
)
def create_forecasts(
    sensor_ids: List[int],
    from_date_str: str = "2015-02-08",
    to_date_str: str = "2015-12-31",
    horizons_as_hours: List[str] = ["1"],
    resolution: Optional[int] = None,
    as_job: bool = False,
):
    """
    Create forecasts.

    For example:

        --from_date 2015-02-02 --to_date 2015-02-04 --horizon_hours 6 --sensor-id 12 --sensor-id 14

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

    event_resolution: Optional[timedelta]
    if resolution is not None:
        event_resolution = timedelta(minutes=resolution)
    else:
        event_resolution = None

    if as_job:
        for sensor_id in sensor_ids:
            for horizon in horizons:
                # Note that this time period refers to the period of events we are forecasting, while in create_forecasting_jobs
                # the time period refers to the period of belief_times, therefore we are subtracting the horizon.
                create_forecasting_jobs(
                    sensor_id=sensor_id,
                    horizons=[horizon],
                    start_of_roll=forecast_start - horizon,
                    end_of_roll=forecast_end - horizon,
                )
    else:
        from flexmeasures.data.scripts.data_gen import populate_time_series_forecasts

        populate_time_series_forecasts(
            db=app.db,
            sensor_ids=sensor_ids,
            horizons=horizons,
            forecast_start=forecast_start,
            forecast_end=forecast_end,
            event_resolution=event_resolution,
        )


@fm_add_data.command("schedule")
@with_appcontext
@click.option(
    "--sensor-id",
    "power_sensor",
    type=SensorIdField(),
    required=True,
    help="Create schedule for this sensor. Follow up with the sensor's ID.",
)
@click.option(
    "--optimization-context-id",
    "optimization_context_sensor",
    type=SensorIdField(),
    required=True,
    help="Optimize against this sensor, which measures a price factor or CO₂ intensity factor. Follow up with the sensor's ID.",
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
    help="Target state of charge (e.g 100%, or 1) at some datetime. Follow up with a float value and a timezone-aware datetime in ISO 6081 format."
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
    type=QuantityField("%", validate=validate.Range(min=0, max=1)),
    required=False,
    default=1,
    help="Round-trip efficiency (e.g. 85% or 0.85) to use for the schedule. Defaults to 100% (no losses).",
)
def create_schedule(
    power_sensor: Sensor,
    optimization_context_sensor: Sensor,
    start: datetime,
    duration: timedelta,
    soc_at_start: ur.Quantity,
    soc_target_strings: List[Tuple[ur.Quantity, str]],
    soc_min: Optional[ur.Quantity] = None,
    soc_max: Optional[ur.Quantity] = None,
    roundtrip_efficiency: Optional[ur.Quantity] = None,
):
    """Create a new schedule for a given power sensor.

    Current limitations:

    - only supports battery assets and Charge Points
    - only supports datetimes on the hour or a multiple of the sensor resolution thereafter
    """

    # Parse input
    if not power_sensor.measures_power:
        click.echo(f"Sensor with ID {power_sensor.id} is not a power sensor.")
        raise click.Abort()
    end = start + duration
    for attribute in ("min_soc_in_mwh", "max_soc_in_mwh"):
        try:
            check_required_attributes(power_sensor, [(attribute, float)])
        except MissingAttributeException:
            click.echo(f"{power_sensor} has no {attribute} attribute.")
            raise click.Abort()
    soc_targets = pd.Series(
        np.nan,
        index=pd.date_range(
            pd.Timestamp(start).tz_convert(power_sensor.timezone),
            pd.Timestamp(end).tz_convert(power_sensor.timezone),
            freq=power_sensor.event_resolution,
            closed="right",
        ),  # note that target values are indexed by their due date (i.e. closed="right")
    )

    # Convert round-trip efficiency to dimensionless
    if roundtrip_efficiency is not None:
        roundtrip_efficiency = roundtrip_efficiency.to(
            ur.Quantity("dimensionless")
        ).magnitude

    # Convert SoC units to MWh, given the storage capacity
    capacity_str = f"{power_sensor.get_attribute('max_soc_in_mwh')} MWh"
    soc_at_start = convert_units(soc_at_start.magnitude, soc_at_start.units, "MWh", capacity=capacity_str)  # type: ignore
    for soc_target_tuple in soc_target_strings:
        soc_target_value_str, soc_target_dt_str = soc_target_tuple
        soc_target_value = convert_units(
            soc_target_value_str.magnitude,
            str(soc_target_value_str.units),
            "MWh",
            capacity=capacity_str,
        )
        soc_target_datetime = pd.Timestamp(soc_target_dt_str)
        soc_targets.loc[soc_target_datetime] = soc_target_value
    if soc_min is not None:
        soc_min = convert_units(soc_min.magnitude, str(soc_min.units), "MWh", capacity=capacity_str)  # type: ignore
    if soc_max is not None:
        soc_max = convert_units(soc_max.magnitude, str(soc_max.units), "MWh", capacity=capacity_str)  # type: ignore

    success = make_schedule(
        sensor_id=power_sensor.id,
        start=start,
        end=end,
        belief_time=server_now(),
        resolution=power_sensor.event_resolution,
        soc_at_start=soc_at_start,
        soc_targets=soc_targets,
        soc_min=soc_min,
        soc_max=soc_max,
        roundtrip_efficiency=roundtrip_efficiency,
        price_sensor=optimization_context_sensor,
    )
    if success:
        print("New schedule is stored.")


@fm_add_data.command("toy-account")
@with_appcontext
@click.option(
    "--kind",
    default="battery",
    type=click.Choice(["battery"]),
    help="What kind of toy account. Defaults to a battery.",
)
@click.option("--name", type=str, default="Toy Account", help="Name of the account")
def add_toy_account(kind: str, name: str):
    """
    Create a toy account, for tutorials and trying things.
    """
    asset_types = add_default_asset_types(db=db)
    location = (52.374, 4.88969)  # Amsterdam
    if kind == "battery":
        # make an account (if not exist)
        account = Account.query.filter(Account.name == name).one_or_none()
        if account:
            click.echo(f"Account {name} already exists. Aborting ...")
            raise click.Abort()
        # make an account user (account-admin?)
        user = create_user(
            email="toy-user@flexmeasures.io",
            check_email_deliverability=False,
            password="toy-password",
            user_roles=["account-admin"],
            account_name=name,
        )
        # make assets
        for asset_type in ("solar", "building", "battery"):
            asset = GenericAsset(
                name=f"toy-{asset_type}",
                generic_asset_type=asset_types[asset_type],
                owner=user.account,
                latitude=location[0],
                longitude=location[1],
            )
            db.session.add(asset)
            if asset_type == "battery":
                asset.attributes = dict(
                    capacity_in_mw=0.5, min_soc_in_mwh=0.05, max_soc_in_mwh=0.45
                )
                # add charging sensor to battery
                charging_sensor = Sensor(
                    name="charging",
                    generic_asset=asset,
                    unit="MW",
                    timezone="Europe/Amsterdam",
                    event_resolution=timedelta(minutes=15),
                )
                db.session.add(charging_sensor)

        # add public day-ahead market (as sensor of transmission zone asset)
        nl_zone = add_transmission_zone_asset("NL", db=db)
        day_ahead_sensor = Sensor.query.filter(
            Sensor.generic_asset == nl_zone, Sensor.name == "Day ahead prices"
        ).one_or_none()
        if not day_ahead_sensor:
            day_ahead_sensor = Sensor(
                name="Day ahead prices",
                generic_asset=nl_zone,
                unit="EUR/MWh",
                timezone="Europe/Amsterdam",
                event_resolution=timedelta(minutes=60),
                knowledge_horizon=(
                    x_days_ago_at_y_oclock,
                    {"x": 1, "y": 12, "z": "Europe/Paris"},
                ),
            )
        db.session.add(day_ahead_sensor)

    db.session.commit()

    click.echo(
        f"Toy account {name} with user {user.email} created successfully. You might want to run `flexmeasures show account --id {user.account.id}`"
    )
    click.echo(f"The sensor for battery charging is {charging_sensor}.")
    click.echo(f"The sensor for Day ahead prices is {day_ahead_sensor}.")


app.cli.add_command(fm_add_data)


def check_timezone(timezone):
    try:
        pytz.timezone(timezone)
    except pytz.UnknownTimeZoneError:
        print("Timezone %s is unknown!" % timezone)
        raise click.Abort


def check_errors(errors: Dict[str, List[str]]):
    if errors:
        print(
            f"Please correct the following errors:\n{errors}.\n Use the --help flag to learn more."
        )
        raise click.Abort
