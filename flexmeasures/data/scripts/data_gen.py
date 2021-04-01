"""
Populate the database with data we know or read in.
"""
from typing import List, Optional
from pathlib import Path
from shutil import rmtree
from datetime import datetime, timedelta

from flask import current_app as app
from flask_sqlalchemy import SQLAlchemy
import click
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.serializer import loads, dumps
from timetomodel.forecasting import make_rolling_forecasts
from timetomodel.exceptions import MissingData, NaNData
import pytz
from humanize import naturaldelta
import inflect

from flexmeasures.data.models.markets import MarketType, Market, Price
from flexmeasures.data.models.assets import AssetType, Asset, Power
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.weather import WeatherSensorType, WeatherSensor, Weather
from flexmeasures.data.models.user import User, Role, RolesUsers
from flexmeasures.data.models.forecasting import lookup_model_specs_configurator
from flexmeasures.data.models.forecasting.exceptions import NotEnoughDataException
from flexmeasures.data.queries.utils import parse_sqlalchemy_results
from flexmeasures.utils.time_utils import ensure_local_timezone
from flexmeasures.data.transactional import as_transaction


BACKUP_PATH = app.config.get("FLEXMEASURES_DB_BACKUP_PATH")
LOCAL_TIME_ZONE = app.config.get("FLEXMEASURES_TIMEZONE")

infl_eng = inflect.engine()


def add_data_sources(db: SQLAlchemy):
    db.session.add(DataSource(name="Seita", type="demo script"))


def add_asset_types(db: SQLAlchemy):
    db.session.add(
        AssetType(
            name="solar",
            display_name="solar panel",
            is_producer=True,
            daily_seasonality=True,
            yearly_seasonality=True,
        )
    )
    db.session.add(
        AssetType(
            name="wind",
            display_name="wind turbine",
            is_producer=True,
            can_curtail=True,
            daily_seasonality=True,
            yearly_seasonality=True,
        )
    )
    db.session.add(
        AssetType(
            name="one-way_evse",
            display_name="one-way EVSE",
            hover_label="uni-directional Electric Vehicle Supply Equipment",
            is_consumer=True,
            can_shift=True,
            daily_seasonality=True,
            weekly_seasonality=True,
            yearly_seasonality=True,
        )
    )
    db.session.add(
        AssetType(
            name="two-way_evse",
            display_name="two-way EVSE",
            hover_label="bi-directional Electric Vehicle Supply Equipment",
            is_consumer=True,
            is_producer=True,
            can_shift=True,
            daily_seasonality=True,
            weekly_seasonality=True,
            yearly_seasonality=True,
        )
    )
    db.session.add(
        AssetType(
            name="battery",
            display_name="stationary battery",
            is_consumer=True,
            is_producer=True,
            can_curtail=True,
            can_shift=True,
            daily_seasonality=True,
            weekly_seasonality=True,
            yearly_seasonality=True,
        )
    )
    db.session.add(
        AssetType(
            name="building",
            display_name="building",
            is_consumer=True,
            is_producer=True,
            can_shift=True,
            daily_seasonality=True,
            weekly_seasonality=True,
            yearly_seasonality=True,
        )
    )


def add_weather_sensor_types(db: SQLAlchemy):
    db.session.add(WeatherSensorType(name="temperature"))
    db.session.add(WeatherSensorType(name="wind_speed"))
    db.session.add(WeatherSensorType(name="radiation"))


def add_market_types(db: SQLAlchemy):
    db.session.add(
        MarketType(
            name="day_ahead",
            display_name="day-ahead market",
            daily_seasonality=True,
            weekly_seasonality=True,
            yearly_seasonality=True,
        )
    )
    db.session.add(
        MarketType(
            name="tou_tariff",
            display_name="time-of use tariff",
            daily_seasonality=True,
            weekly_seasonality=False,
            yearly_seasonality=True,
        )
    )


def add_dummy_tou_market(db: SQLAlchemy):
    """
    Add a dummy time-of-use market with a 1-year resolution.
    Also add a few price points, each covering a whole year.

    Note that for this market, the leap years will not have a price on
    December 31st. To fix that, we should use 366 days as resolution,
    but test what that involves on that day, or we need timely-beliefs to switch
    to defining sensor event resolutions as nominal durations.
    """
    market = Market(
        name="dummy-tou",
        event_resolution=timedelta(days=365),
        market_type_name="tou_tariff",
        unit="EUR/MWh",
    )
    db.session.add(market)
    source = DataSource.query.filter(DataSource.name == "Seita").one_or_none()
    for year in range(2015, 2025):
        db.session.add(
            Price(
                value=50,
                datetime=datetime(year, 1, 1, tzinfo=pytz.utc),
                horizon=timedelta(0),
                data_source_id=source.id,
                market=market,
            )
        )


# ------------ Main functions --------------------------------
# These can registered at the app object as cli functions


@as_transaction
def populate_structure(db: SQLAlchemy):
    """
    Add initial structural data for assets, markets, data sources

    TODO: add user roles (they can get created on-the-fly, but we should be
          more pro-active)
    """
    click.echo("Populating the database %s with structural data ..." % db.engine)
    add_data_sources(db)
    add_asset_types(db)
    add_weather_sensor_types(db)
    add_market_types(db)
    add_dummy_tou_market(db)
    click.echo("DB now has %d AssetType(s)" % db.session.query(AssetType).count())
    click.echo(
        "DB now has %d WeatherSensorType(s)"
        % db.session.query(WeatherSensorType).count()
    )
    click.echo("DB now has %d MarketType(s)" % db.session.query(MarketType).count())
    click.echo("DB now has %d Market(s)" % db.session.query(Market).count())


@as_transaction  # noqa: C901
def populate_time_series_forecasts(  # noqa: C901
    db: SQLAlchemy,
    horizons: List[timedelta],
    start: datetime,
    end: datetime,
    generic_asset_type: Optional[str] = None,
    generic_asset_id: Optional[int] = None,
):
    training_and_testing_period = timedelta(days=30)

    click.echo(
        "Populating the database %s with time series forecasts of %s ahead ..."
        % (db.engine, infl_eng.join([naturaldelta(horizon) for horizon in horizons]))
    )

    # Set a data source for the forecasts
    data_source = DataSource.query.filter_by(
        name="Seita", type="demo script"
    ).one_or_none()

    # List all generic assets for which to forecast.
    # Look into asset type if no asset name is given. If an asset name is given,
    generic_assets = []
    if generic_asset_id is None:
        if generic_asset_type is None or generic_asset_type == "WeatherSensor":
            sensors = WeatherSensor.query.all()
            generic_assets.extend(sensors)
        if generic_asset_type is None or generic_asset_type == "Asset":
            assets = Asset.query.all()
            generic_assets.extend(assets)
        if generic_asset_type is None or generic_asset_type == "Market":
            markets = Market.query.all()
            generic_assets.extend(markets)
    else:
        if generic_asset_type is None:
            click.echo(
                "If you specify --asset-name, please also specify --asset-type, so we can look it up."
            )
            return
        if generic_asset_type == "WeatherSensor":
            sensors = WeatherSensor.query.filter(
                WeatherSensor.id == generic_asset_id
            ).one_or_none()
            if sensors is not None:
                generic_assets.append(sensors)
        if generic_asset_type == "Asset":
            assets = Asset.query.filter(Asset.id == generic_asset_id).one_or_none()
            if assets is not None:
                generic_assets.append(assets)
        if generic_asset_type == "Market":
            markets = Market.query.filter(Market.id == generic_asset_id).one_or_none()
            if markets is not None:
                generic_assets.append(markets)
    if not generic_assets:
        click.echo("No such assets in db, so I will not add any forecasts.")
        return

    # Make a model for each asset and horizon, make rolling forecasts and save to database.
    # We cannot use (faster) bulk save, as forecasts might become regressors in other forecasts.
    for generic_asset in generic_assets:
        for horizon in horizons:
            try:
                default_model = lookup_model_specs_configurator()
                model_specs, model_identifier, model_fallback = default_model(
                    generic_asset=generic_asset,
                    forecast_start=start,
                    forecast_end=end,
                    forecast_horizon=horizon,
                    custom_model_params=dict(
                        training_and_testing_period=training_and_testing_period
                    ),
                )
                click.echo(
                    "Computing forecasts of %s ahead for %s, "
                    "from %s to %s with a training and testing period of %s, using %s ..."
                    % (
                        naturaldelta(horizon),
                        generic_asset.name,
                        start,
                        end,
                        naturaldelta(training_and_testing_period),
                        model_identifier,
                    )
                )
                model_specs.creation_time = start
                forecasts, model_state = make_rolling_forecasts(
                    start=start, end=end, model_specs=model_specs
                )
            except (NotEnoughDataException, MissingData, NaNData) as e:
                click.echo(
                    "Skipping forecasts for asset %s: %s" % (generic_asset, str(e))
                )
                continue
            """
            import matplotlib.pyplot as plt
            plt.plot(
                model_state.specs.outcome_var.load_series().loc[
                    pd.date_range(start, end=end, freq="15T")
                ],
                label="y",
            )
            plt.plot(forecasts, label="y^hat")
            plt.legend()
            plt.show()
            """

            beliefs = []
            if isinstance(generic_asset, Asset):
                beliefs = [
                    Power(
                        datetime=ensure_local_timezone(dt, tz_name=LOCAL_TIME_ZONE),
                        horizon=horizon,
                        value=value,
                        asset_id=generic_asset.id,
                        data_source_id=data_source.id,
                    )
                    for dt, value in forecasts.items()
                ]
            elif isinstance(generic_asset, Market):
                beliefs = [
                    Price(
                        datetime=ensure_local_timezone(dt, tz_name=LOCAL_TIME_ZONE),
                        horizon=horizon,
                        value=value,
                        market_id=generic_asset.id,
                        data_source_id=data_source.id,
                    )
                    for dt, value in forecasts.items()
                ]
            elif isinstance(generic_asset, WeatherSensor):
                beliefs = [
                    Weather(
                        datetime=ensure_local_timezone(dt, tz_name=LOCAL_TIME_ZONE),
                        horizon=horizon,
                        value=value,
                        sensor_id=generic_asset.id,
                        data_source_id=data_source.id,
                    )
                    for dt, value in forecasts.items()
                ]

            print(
                "Saving %s %s-forecasts for %s..."
                % (len(beliefs), naturaldelta(horizon), generic_asset.name)
            )
            for belief in beliefs:
                db.session.add(belief)

    click.echo(
        "DB now has %d Power Forecasts"
        % db.session.query(Power).filter(Power.horizon > timedelta(hours=0)).count()
    )
    click.echo(
        "DB now has %d Price Forecasts"
        % db.session.query(Price).filter(Price.horizon > timedelta(hours=0)).count()
    )
    click.echo(
        "DB now has %d Weather Forecasts"
        % db.session.query(Weather).filter(Weather.horizon > timedelta(hours=0)).count()
    )


@as_transaction
def depopulate_structure(db: SQLAlchemy):
    click.echo("Depopulating structural data from the database %s ..." % db.engine)
    num_assets_deleted = db.session.query(Asset).delete()
    num_asset_types_deleted = db.session.query(AssetType).delete()
    num_markets_deleted = db.session.query(Market).delete()
    num_market_types_deleted = db.session.query(MarketType).delete()
    num_sensors_deleted = db.session.query(WeatherSensor).delete()
    num_sensor_types_deleted = db.session.query(WeatherSensorType).delete()
    num_data_sources_deleted = db.session.query(DataSource).delete()
    roles = db.session.query(Role).all()
    num_roles_deleted = 0
    for role in roles:
        db.session.delete(role)
        num_roles_deleted += 1
    users = db.session.query(User).all()
    num_users_deleted = 0
    for user in users:
        db.session.delete(user)
        num_users_deleted += 1
    click.echo("Deleted %d MarketTypes" % num_market_types_deleted)
    click.echo("Deleted %d Markets" % num_markets_deleted)
    click.echo("Deleted %d WeatherSensorTypes" % num_sensor_types_deleted)
    click.echo("Deleted %d WeatherSensors" % num_sensors_deleted)
    click.echo("Deleted %d AssetTypes" % num_asset_types_deleted)
    click.echo("Deleted %d Assets" % num_assets_deleted)
    click.echo("Deleted %d DataSources" % num_data_sources_deleted)
    click.echo("Deleted %d Roles" % num_roles_deleted)
    click.echo("Deleted %d Users" % num_users_deleted)


@as_transaction
def depopulate_measurements(
    db: SQLAlchemy,
    generic_asset_type: Optional[str] = None,
    generic_asset_id: Optional[id] = None,
):
    click.echo("Depopulating (time series) data from the database %s ..." % db.engine)
    num_prices_deleted = 0
    num_power_measurements_deleted = 0
    num_weather_measurements_deleted = 0

    # TODO: simplify this when sensors moved to one unified table

    if generic_asset_id is None:
        if generic_asset_type is None or generic_asset_type == "Market":
            num_prices_deleted = (
                db.session.query(Price)
                .filter(Price.horizon <= timedelta(hours=0))
                .delete()
            )
        if generic_asset_type is None or generic_asset_type == "Asset":
            num_power_measurements_deleted = (
                db.session.query(Power)
                .filter(Power.horizon <= timedelta(hours=0))
                .delete()
            )
        if generic_asset_type is None or generic_asset_type == "WeatherSensor":
            num_weather_measurements_deleted = (
                db.session.query(Weather)
                .filter(Weather.horizon <= timedelta(hours=0))
                .delete()
            )
    else:
        if generic_asset_type is None:
            click.echo(
                "If you specify --asset-name, please also specify --asset-type, so we can look it up."
            )
            return
        if generic_asset_type == "Market":
            market = (
                db.session.query(Market)
                .filter(Market.id == generic_asset_id)
                .one_or_none()
            )
            if market is not None:
                num_prices_deleted = (
                    db.session.query(Price)
                    .filter(Price.horizon <= timedelta(hours=0))
                    .filter(Price.market == market)
                    .delete()
                )
            else:
                num_prices_deleted = 0

        elif generic_asset_type == "Asset":
            asset = (
                db.session.query(Asset)
                .filter(Asset.id == generic_asset_id)
                .one_or_none()
            )
            if asset is not None:
                num_power_measurements_deleted = (
                    db.session.query(Power)
                    .filter(Power.horizon <= timedelta(hours=0))
                    .filter(Power.asset == asset)
                    .delete()
                )
            else:
                num_power_measurements_deleted = 0

        elif generic_asset_type == "WeatherSensor":
            sensor = (
                db.session.query(WeatherSensor)
                .filter(WeatherSensor.id == generic_asset_id)
                .one_or_none()
            )
            if sensor is not None:
                num_weather_measurements_deleted = (
                    db.session.query(Weather)
                    .filter(Weather.horizon <= timedelta(hours=0))
                    .filter(Weather.sensor == sensor)
                    .delete()
                )
            else:
                num_weather_measurements_deleted = 0

    click.echo("Deleted %d Prices" % num_prices_deleted)
    click.echo("Deleted %d Power Measurements" % num_power_measurements_deleted)
    click.echo("Deleted %d Weather Measurements" % num_weather_measurements_deleted)


@as_transaction
def depopulate_prognoses(
    db: SQLAlchemy,
    generic_asset_type: Optional[str] = None,
    generic_asset_id: Optional[id] = None,
):
    click.echo(
        "Depopulating (time series) forecasts and schedules data from the database %s ..."
        % db.engine
    )
    num_prices_deleted = 0
    num_power_measurements_deleted = 0
    num_weather_measurements_deleted = 0

    # Clear all jobs
    num_forecasting_jobs_deleted = app.queues["forecasting"].empty()
    num_scheduling_jobs_deleted = app.queues["scheduling"].empty()

    # Clear all forecasts (data with positive horizon)
    if generic_asset_id is None:
        if generic_asset_type is None or generic_asset_type == "Market":
            num_prices_deleted = (
                db.session.query(Price)
                .filter(Price.horizon > timedelta(hours=0))
                .delete()
            )
        if generic_asset_type is None or generic_asset_type == "Asset":
            num_power_measurements_deleted = (
                db.session.query(Power)
                .filter(Power.horizon > timedelta(hours=0))
                .delete()
            )
        if generic_asset_type is None or generic_asset_type == "WeatherSensor":
            num_weather_measurements_deleted = (
                db.session.query(Weather)
                .filter(Weather.horizon > timedelta(hours=0))
                .delete()
            )
    else:
        click.echo(
            "Depopulating (time series) forecasts and schedules for %s from the database %s ..."
            % (generic_asset_id, db.engine)
        )

        if generic_asset_type == "Market":
            market = (
                db.session.query(Market)
                .filter(Market.id == generic_asset_id)
                .one_or_none()
            )
            if market is not None:
                num_prices_deleted = (
                    db.session.query(Price)
                    .filter(Price.horizon > timedelta(hours=0))
                    .filter(Price.market == market)
                    .delete()
                )
            else:
                num_prices_deleted = 0

        if generic_asset_type == "Asset":
            asset = (
                db.session.query(Asset)
                .filter(Asset.id == generic_asset_id)
                .one_or_none()
            )
            if asset is not None:
                num_power_measurements_deleted = (
                    db.session.query(Power)
                    .filter(Power.horizon > timedelta(hours=0))
                    .filter(Power.asset == asset)
                    .delete()
                )
            else:
                num_power_measurements_deleted = 0

        if generic_asset_type == "WeatherSensor":
            sensor = (
                db.session.query(WeatherSensor)
                .filter(WeatherSensor.id == generic_asset_id)
                .one_or_none()
            )
            if sensor is not None:
                num_weather_measurements_deleted = (
                    db.session.query(Weather)
                    .filter(Weather.horizon > timedelta(hours=0))
                    .filter(Weather.sensor == sensor)
                    .delete()
                )
            else:
                num_weather_measurements_deleted = 0
    click.echo("Deleted %d Forecast Jobs" % num_forecasting_jobs_deleted)
    click.echo("Deleted %d Schedule Jobs" % num_scheduling_jobs_deleted)
    click.echo("Deleted %d Price Forecasts" % num_prices_deleted)
    click.echo("Deleted %d Power Forecasts" % num_power_measurements_deleted)
    click.echo("Deleted %d Weather Forecasts" % num_weather_measurements_deleted)


def reset_db(db: SQLAlchemy):
    db.session.commit()  # close any existing sessions
    click.echo("Dropping everything in %s ..." % db.engine)
    db.reflect()  # see http://jrheard.tumblr.com/post/12759432733/dropping-all-tables-on-postgres-using
    db.drop_all()
    click.echo("Recreating everything ...")
    db.create_all()
    click.echo("Committing ...")
    db.session.commit()


def save_tables(
    db: SQLAlchemy,
    backup_name: str = "",
    structure: bool = True,
    data: bool = False,
    backup_path: str = BACKUP_PATH,
):
    # Make a new folder for the backup
    backup_folder = Path("%s/%s" % (backup_path, backup_name))
    try:
        backup_folder.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        click.echo(
            "Can't save backup, because directory %s/%s already exists."
            % (backup_path, backup_name)
        )
        return

    affected_classes = get_affected_classes(structure, data)
    c = None
    try:
        for c in affected_classes:
            file_path = "%s/%s/%s.obj" % (backup_path, backup_name, c.__tablename__)

            with open(file_path, "xb") as file_handler:
                file_handler.write(dumps(db.session.query(c).all()))
            click.echo("Successfully saved %s/%s." % (backup_name, c.__tablename__))
    except SQLAlchemyError as e:
        click.echo(
            "Can't save table %s because of the following error:\n\n\t%s\n\nCleaning up..."
            % (c.__tablename__, e)
        )
        rmtree(backup_folder)
        click.echo("Removed directory %s/%s." % (backup_path, backup_name))


@as_transaction
def load_tables(
    db: SQLAlchemy,
    backup_name: str = "",
    structure: bool = True,
    data: bool = False,
    backup_path: str = BACKUP_PATH,
):
    if (
        Path("%s/%s" % (backup_path, backup_name)).exists()
        and Path("%s/%s" % (backup_path, backup_name)).is_dir()
    ):
        affected_classes = get_affected_classes(structure, data)
        statement = "SELECT sequence_name from information_schema.sequences;"
        data = db.session.execute(statement).fetchall()
        sequence_names = [s["sequence_name"] for s in parse_sqlalchemy_results(data)]
        for c in affected_classes:
            file_path = "%s/%s/%s.obj" % (backup_path, backup_name, c.__tablename__)
            sequence_name = "%s_id_seq" % c.__tablename__
            try:
                with open(file_path, "rb") as file_handler:
                    for row in loads(file_handler.read()):
                        db.session.merge(row)
                if sequence_name in sequence_names:

                    # Get max id
                    max_id = db.session.query(func.max(c.id)).one_or_none()[0]
                    max_id = 1 if max_id is None else max_id

                    # Set table seq to max id
                    db.engine.execute(
                        "SELECT setval('%s', %s, true);" % (sequence_name, max_id)
                    )

                click.echo(
                    "Successfully loaded %s/%s." % (backup_name, c.__tablename__)
                )
            except FileNotFoundError:
                click.echo(
                    "Can't load table, because filename %s does not exist."
                    % c.__tablename__
                )
    else:
        click.echo(
            "Can't load backup, because directory %s/%s does not exist."
            % (backup_path, backup_name)
        )


def get_affected_classes(structure: bool = True, data: bool = False) -> List:
    affected_classes = []
    if structure:
        affected_classes += [
            Role,
            User,
            RolesUsers,
            MarketType,
            Market,
            AssetType,
            Asset,
            WeatherSensorType,
            WeatherSensor,
            DataSource,
        ]
    if data:
        affected_classes += [Power, Price, Weather]
    return affected_classes
