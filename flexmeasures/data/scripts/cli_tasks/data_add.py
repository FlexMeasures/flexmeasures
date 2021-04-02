"""CLI Tasks for (de)populating the database - most useful in development"""

from datetime import timedelta
from typing import List

import pandas as pd
import pytz
from flask import current_app as app
from flask.cli import with_appcontext
from flask_security.utils import hash_password
import click
import getpass

from flexmeasures.data.services.forecasting import create_forecasting_jobs
from flexmeasures.data.services.users import create_user
from flexmeasures.data.models.assets import Asset, AssetSchema
from flexmeasures.data.models.markets import Market
from flexmeasures.data.models.weather import WeatherSensor, WeatherSensorSchema


@click.group("add")
def fm_add_data():
    """FlexMeasures: Add data."""


@fm_add_data.command("user")
@with_appcontext
@click.option("--username", required=True)
@click.option("--email", required=True)
@click.option("--roles", help="e.g. anonymous,Prosumer,CPO")
@click.option(
    "--timezone",
    default="UTC",
    help="timezone as string, e.g. 'UTC' or 'Europe/Amsterdam'",
)
def new_user(username: str, email: str, roles: List[str], timezone: str):
    """
    Create a FlexMeasures user.

    The `users create` task from Flask Security Too is too simple for us.
    Use this to add email, timezone and roles.
    """
    try:
        pytz.timezone(timezone)
    except pytz.UnknownTimeZoneError:
        print("Timezone %s is unknown!" % timezone)
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
        timezone=timezone,
        user_roles=roles,
        check_deliverability=False,
    )
    app.db.session.commit()
    print(f"Successfully created user {created_user}")


@fm_add_data.command("asset")
@with_appcontext
@click.option("--name", required=True)
@click.option("--asset-type-name", required=True)
@click.option("--unit", required=True, help="e.g. MW, kW/h", default="MW")
@click.option("--capacity-in-MW", required=True, type=float)
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
    app.db.session.add(asset)
    app.db.session.commit()
    print(f"Successfully created asset with ID:{asset.id}.")
    print(f" You can access it at its entity address {asset.entity_address}")


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
    app.db.session.add(sensor)
    app.db.session.commit()
    print(f"Successfully created sensor with ID:{sensor.id}.")
    # TODO: uncomment when #66 has landed
    # print(f" You can access it at its entity address {sensor.entity_address}")


@fm_add_data.command("structure")
@with_appcontext
def add_initial_structure():
    """Initialize structural data like asset types, market types and weather sensor types."""
    from flexmeasures.data.scripts.data_gen import populate_structure

    populate_structure(app.db)


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
    default="2015-02-08",
    help="Forecast from date (inclusive). Follow up with a date in the form yyyy-mm-dd.",
)
@click.option(
    "--to-date",
    default="2015-12-31",
    help="Forecast to date (inclusive). Follow up with a date in the form yyyy-mm-dd.",
)
@click.option(
    "--horizon",
    "horizons",
    multiple=True,
    type=click.Choice(["1", "6", "24", "48"]),
    default=["1", "6", "24", "48"],
    help="Forecasting horizon in hours. This argument can be given multiple times.",
)
@click.option(
    "--as-job",
    is_flag=True,
    help="Whether to queue a forecasting job instead of computing directly."
    " Useful to run locally and create forecasts on a remote server. In that case, just point the redis db in your"
    " config settings to that of the remote server. To process the job, run a worker to process the forecasting queue.",
)
def create_forecasts(
    asset_type: str = None,
    asset_id: int = None,
    from_date: str = "2015-02-08",
    to_date: str = "2015-12-31",
    horizons: List[str] = ["1"],
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
    horizons = [timedelta(hours=int(h)) for h in horizons]

    # apply timezone:
    timezone = app.config.get("FLEXMEASURES_TIMEZONE")
    from_date = pd.Timestamp(from_date).tz_localize(timezone)
    to_date = pd.Timestamp(to_date).tz_localize(timezone)

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
                start_of_roll=from_date - timedelta(hours=horizon),
                end_of_roll=to_date - timedelta(hours=horizon),
            )
    else:
        from flexmeasures.data.scripts.data_gen import populate_time_series_forecasts

        populate_time_series_forecasts(
            app.db, horizons, from_date, to_date, asset_type, asset_id
        )


@fm_add_data.command("external-weather-forecasts")
@click.option(
    "--region",
    type=str,
    default="",
    help="Name of the region (will create sub-folder, should later tag the forecast in the DB, probably).",
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
    help="Number of cells on the grid. Only used if a region of interest has been mapped in the location parameter.",
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
    help="Store forecasts in the database, or simply save as json files.",
)
def collect_weather_data(region, location, num_cells, method, store_in_db):
    """
    Collect weather forecasts from the DarkSky API

    This function can get weather data for one location or for several location within
    a geometrical grid (See the --location parameter).
    """
    from flexmeasures.data.scripts.grid_weather import get_weather_forecasts

    get_weather_forecasts(app, region, location, num_cells, method, store_in_db)


app.cli.add_command(fm_add_data)


def check_timezone(timezone):
    try:
        pytz.timezone(timezone)
    except pytz.UnknownTimeZoneError:
        print("Timezone %s is unknown!" % timezone)
        raise click.Abort


def check_errors(errors: list):
    if errors:
        print(
            f"Please correct the following errors:\n{errors}.\n Use the --help flag to learn more."
        )
        raise click.Abort
