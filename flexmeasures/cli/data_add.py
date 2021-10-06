"""CLI Tasks for (de)populating the database - most useful in development"""

from datetime import timedelta
from typing import Dict, List, Optional

import pandas as pd
import pytz
from flask import current_app as app
from flask.cli import with_appcontext
from flask_security.utils import hash_password
import click
import getpass
from sqlalchemy.exc import IntegrityError
import timely_beliefs as tb

from flexmeasures.data import db
from flexmeasures.data.services.forecasting import create_forecasting_jobs
from flexmeasures.data.services.users import create_user
from flexmeasures.data.models.user import Account, AccountRole, RolesAccounts
from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.data.schemas.sensors import SensorSchema
from flexmeasures.data.schemas.generic_assets import (
    GenericAssetSchema,
    GenericAssetTypeSchema,
)
from flexmeasures.data.models.assets import Asset
from flexmeasures.data.schemas.assets import AssetSchema
from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.models.markets import Market
from flexmeasures.data.models.weather import WeatherSensor
from flexmeasures.data.schemas.weather import WeatherSensorSchema
from flexmeasures.data.models.data_sources import (
    get_or_create_source,
    get_source_or_none,
)
from flexmeasures.utils.time_utils import server_now


@click.group("add")
def fm_add_data():
    """FlexMeasures: Add data."""


@click.group("dev-add")
def fm_dev_add_data():
    """Developer CLI commands not yet meant for users: Add data."""


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
        print(f"No account with id {account_id} found!")
        raise click.Abort
    pwd1 = getpass.getpass(prompt="Please enter the password:")
    pwd2 = getpass.getpass(prompt="Please repeat the password:")
    if pwd1 != pwd2:
        print("Passwords do not match!")
        raise click.Abort
    created_user = create_user(
        username=username,
        email=email,
        password=hash_password(pwd1),
        account_name=account.name,
        timezone=timezone,
        user_roles=roles,
        check_email_deliverability=False,
    )
    db.session.commit()
    print(f"Successfully created user {created_user}")


@fm_dev_add_data.command("sensor")
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
    "--generic-asset-id",
    required=True,
    type=int,
    help="Generic asset to assign this sensor to",
)
def add_sensor(**args):
    """Add a sensor."""
    check_timezone(args["timezone"])
    check_errors(SensorSchema().validate(args))
    args["event_resolution"] = timedelta(minutes=args["event_resolution"])
    sensor = Sensor(**args)
    db.session.add(sensor)
    db.session.commit()
    print(f"Successfully created sensor with ID {sensor.id}")
    print(f"You can access it at its entity address {sensor.entity_address}")


@fm_dev_add_data.command("generic-asset-type")
@with_appcontext
@click.option("--name", required=True)
@click.option(
    "--description",
    type=str,
    help="Description (useful to explain acronyms, for example).",
)
def add_generic_asset_type(**args):
    """Add a generic asset type."""
    check_errors(GenericAssetTypeSchema().validate(args))
    generic_asset_type = GenericAssetType(**args)
    db.session.add(generic_asset_type)
    db.session.commit()
    print(f"Successfully created generic asset type with ID {generic_asset_type.id}")
    print("You can now assign generic assets to it")


@fm_dev_add_data.command("generic-asset")
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
    "--generic-asset-type-id",
    required=True,
    type=int,
    help="Generic asset type to assign to this asset",
)
def add_generic_asset(**args):
    """Add a generic asset."""
    check_errors(GenericAssetSchema().validate(args))
    generic_asset = GenericAsset(**args)
    db.session.add(generic_asset)
    db.session.commit()
    print(f"Successfully created generic asset with ID {generic_asset.id}")
    print("You can now assign sensors to it")


@fm_add_data.command("asset")
@with_appcontext
@click.option("--name", required=True)
@click.option("--asset-type-name", required=True)
@click.option(
    "--unit",
    help="unit of rate, just MW (default) for now",
    type=click.Choice(["MW"]),
    default="MW",
)  # TODO: enable others
@click.option(
    "--capacity-in-MW",
    required=True,
    type=float,
    help="Maximum rate of this asset in MW",
)
@click.option(
    "--event-resolution",
    required=True,
    type=int,
    help="Expected resolution of the data in minutes",
)
@click.option(
    "--latitude",
    required=True,
    type=float,
    help="Latitude of the asset's location",
)
@click.option(
    "--longitude",
    required=True,
    type=float,
    help="Longitude of the asset's location",
)
@click.option(
    "--owner-id", required=True, type=int, help="Id of the user who owns this asset."
)
@click.option(
    "--market-id",
    type=int,
    help="Id of the market used to price this asset. Defaults to a dummy TOU market.",
)
@click.option(
    "--timezone",
    default="UTC",
    help="timezone as string, e.g. 'UTC' (default) or 'Europe/Amsterdam'.",
)
def new_asset(**args):
    """
    Create a new asset.
    """
    check_timezone(args["timezone"])
    # if no market given, select dummy market
    if args["market_id"] is None:
        dummy_market = Market.query.filter(Market.name == "dummy-tou").one_or_none()
        if not dummy_market:
            print(
                "No market ID given and also no dummy TOU market available. Maybe add structure first."
            )
            raise click.Abort()
        args["market_id"] = dummy_market.id
    check_errors(AssetSchema().validate(args))
    args["event_resolution"] = timedelta(minutes=args["event_resolution"])
    asset = Asset(**args)
    db.session.add(asset)
    db.session.commit()
    print(f"Successfully created asset with ID {asset.id}")
    print(f"You can access it at its entity address {asset.entity_address}")


@fm_add_data.command("weather-sensor")
@with_appcontext
@click.option("--name", required=True)
@click.option("--weather-sensor-type-name", required=True)
@click.option("--unit", required=True, help="e.g. °C, m/s, kW/m²")
@click.option(
    "--event-resolution",
    required=True,
    type=int,
    help="Expected resolution of the data in minutes",
)
@click.option(
    "--latitude",
    required=True,
    type=float,
    help="Latitude of the sensor's location",
)
@click.option(
    "--longitude",
    required=True,
    type=float,
    help="Longitude of the sensor's location",
)
@click.option(
    "--timezone",
    default="UTC",
    help="timezone as string, e.g. 'UTC' (default) or 'Europe/Amsterdam'",
)
def add_weather_sensor(**args):
    """Add a weather sensor."""
    check_timezone(args["timezone"])
    check_errors(WeatherSensorSchema().validate(args))
    args["event_resolution"] = timedelta(minutes=args["event_resolution"])
    sensor = WeatherSensor(**args)
    db.session.add(sensor)
    db.session.commit()
    print(f"Successfully created weather sensor with ID {sensor.id}")
    print(f" You can access it at its entity address {sensor.entity_address}")


@fm_add_data.command("structure")
@with_appcontext
def add_initial_structure():
    """Initialize structural data like asset types, market types and weather sensor types."""
    from flexmeasures.data.scripts.data_gen import populate_structure

    populate_structure(db)


@fm_dev_add_data.command("beliefs")
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
    default="",
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
    horizon: Optional[int] = None,
    cp: Optional[float] = None,
    allow_overwrite: bool = False,
    skiprows: int = 1,
    nrows: Optional[int] = None,
    datecol: int = 0,
    valuecol: int = 1,
    delimiter: str = ",",
    decimal: str = ".",
    thousands: str = "",
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
        print(f"Failed to create beliefs: no sensor found with id {sensor_id}.")
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
        header=None,
        skiprows=skiprows,
        nrows=nrows,
        usecols=[datecol, valuecol],
        parse_dates=True,
        **kwargs,
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


@fm_add_data.command("forecasts")
@with_appcontext
@click.option(
    "--asset-type",
    type=click.Choice(["Asset", "Market", "WeatherSensor"]),
    help="The generic asset type for which to generate forecasts."
    " Follow up with Asset, Market or WeatherSensor.",
)
@click.option(
    "--asset-id",
    help="Populate (time series) data for a single asset only. Follow up with the asset's ID. "
    "We still need --asset-type, as well, so we know where to look this ID up.",
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
    asset_type: str = None,
    asset_id: int = None,
    from_date_str: str = "2015-02-08",
    to_date_str: str = "2015-12-31",
    horizons_as_hours: List[str] = ["1"],
    as_job: bool = False,
):
    """
    Create forecasts.

    For example:

        --from_date 2015-02-02 --to_date 2015-02-04 --horizon_hours 6

        This will create forecast values from 0am on May 2nd to 0am on May 4th,
        based on a 6 hour horizon.

    """
    # make horizons
    horizons = [timedelta(hours=int(h)) for h in horizons_as_hours]

    # apply timezone:
    timezone = app.config.get("FLEXMEASURES_TIMEZONE")
    from_date = pd.Timestamp(from_date_str).tz_localize(timezone)
    to_date = pd.Timestamp(to_date_str).tz_localize(timezone)

    if as_job:
        if asset_type == "Asset":
            value_type = "Power"
        if asset_type == "Market":
            value_type = "Price"
        if asset_type == "WeatherSensor":
            value_type = "Weather"

        for horizon in horizons:
            # Note that this time period refers to the period of events we are forecasting, while in create_forecasting_jobs
            # the time period refers to the period of belief_times, therefore we are subtracting the horizon.
            create_forecasting_jobs(
                asset_id=asset_id,
                timed_value_type=value_type,
                horizons=[horizon],
                start_of_roll=from_date - horizon,
                end_of_roll=to_date - horizon,
            )
    else:
        from flexmeasures.data.scripts.data_gen import populate_time_series_forecasts

        populate_time_series_forecasts(
            db, horizons, from_date, to_date, asset_type, asset_id
        )


@fm_add_data.command("external-weather-forecasts")
@with_appcontext
@click.option(
    "--region",
    type=str,
    default="",
    help="Name of the region (will create sub-folder if you store json files, should later probably tag the forecast in the DB).",
)
@click.option(
    "--location",
    type=str,
    required=True,
    help='Measurement location(s). "latitude,longitude" or "top-left-latitude,top-left-longitude:'
    'bottom-right-latitude,bottom-right-longitude." The first format defines one location to measure.'
    " The second format defines a region of interest with several (>=4) locations"
    ' (see also the "method" and "num_cells" parameters for this feature).',
)
@click.option(
    "--num_cells",
    type=int,
    default=1,
    help="Number of cells on the grid. Only used if a region of interest has been mapped in the location parameter. Defaults to 1.",
)
@click.option(
    "--method",
    default="hex",
    type=click.Choice(["hex", "square"]),
    help="Grid creation method. Only used if a region of interest has been mapped in the location parameter.",
)
@click.option(
    "--store-in-db/--store-as-json-files",
    default=False,
    help="Store forecasts in the database, or simply save as json files. (defaults to json files)",
)
def collect_weather_data(region, location, num_cells, method, store_in_db):
    """
    Collect weather forecasts from the OpenWeatherMap API

    This function can get weather data for one location or for several locations within
    a geometrical grid (See the --location parameter).
    """
    from flexmeasures.data.scripts.grid_weather import get_weather_forecasts

    get_weather_forecasts(app, region, location, num_cells, method, store_in_db)


app.cli.add_command(fm_add_data)
app.cli.add_command(fm_dev_add_data)


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
