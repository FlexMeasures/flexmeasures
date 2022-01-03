"""
Populate the database with data we know or read in.
"""
from typing import List, Optional
from pathlib import Path
from shutil import rmtree
from datetime import datetime, timedelta

import pandas as pd
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

from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.data.models.markets import MarketType, Market
from flexmeasures.data.models.assets import AssetType, Asset
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.weather import WeatherSensorType, WeatherSensor
from flexmeasures.data.models.user import User, Role, RolesUsers
from flexmeasures.data.models.forecasting import lookup_model_specs_configurator
from flexmeasures.data.models.forecasting.exceptions import NotEnoughDataException
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
    source = DataSource.query.filter(
        DataSource.name == "Seita", DataSource.type == "demo script"
    ).one_or_none()
    for year in range(2015, 2025):
        db.session.add(
            TimedBelief(
                event_value=50,
                event_start=datetime(year, 1, 1, tzinfo=pytz.utc),
                belief_horizon=timedelta(0),
                source=source,
                sensor=market.corresponding_sensor,
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
    forecast_start: datetime,
    forecast_end: datetime,
    event_resolution: Optional[timedelta] = None,
    old_sensor_class_name: Optional[str] = None,
    old_sensor_id: Optional[int] = None,
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

    # List all old sensors for which to forecast.
    # Look into their type if no name is given. If a name is given,
    old_sensors = []
    if old_sensor_id is None:
        if old_sensor_class_name is None or old_sensor_class_name == "WeatherSensor":
            sensors = WeatherSensor.query.all()
            old_sensors.extend(sensors)
        if old_sensor_class_name is None or old_sensor_class_name == "Asset":
            assets = Asset.query.all()
            old_sensors.extend(assets)
        if old_sensor_class_name is None or old_sensor_class_name == "Market":
            markets = Market.query.all()
            old_sensors.extend(markets)
    else:
        if old_sensor_class_name is None:
            click.echo(
                "If you specify --asset-name, please also specify --asset-type, so we can look it up."
            )
            return
        if old_sensor_class_name == "WeatherSensor":
            sensors = WeatherSensor.query.filter(
                WeatherSensor.id == old_sensor_id
            ).one_or_none()
            if sensors is not None:
                old_sensors.append(sensors)
        if old_sensor_class_name == "Asset":
            assets = Asset.query.filter(Asset.id == old_sensor_id).one_or_none()
            if assets is not None:
                old_sensors.append(assets)
        if old_sensor_class_name == "Market":
            markets = Market.query.filter(Market.id == old_sensor_id).one_or_none()
            if markets is not None:
                old_sensors.append(markets)
    if not old_sensors:
        click.echo("No such assets in db, so I will not add any forecasts.")
        return

    # Make a model for each old sensor and horizon, make rolling forecasts and save to database.
    # We cannot use (faster) bulk save, as forecasts might become regressors in other forecasts.
    for old_sensor in old_sensors:
        for horizon in horizons:
            try:
                default_model = lookup_model_specs_configurator()
                model_specs, model_identifier, model_fallback = default_model(
                    sensor=old_sensor.corresponding_sensor,
                    forecast_start=forecast_start,
                    forecast_end=forecast_end,
                    forecast_horizon=horizon,
                    custom_model_params=dict(
                        training_and_testing_period=training_and_testing_period,
                        event_resolution=event_resolution,
                    ),
                )
                click.echo(
                    "Computing forecasts of %s ahead for %s, "
                    "from %s to %s with a training and testing period of %s, using %s ..."
                    % (
                        naturaldelta(horizon),
                        old_sensor.name,
                        forecast_start,
                        forecast_end,
                        naturaldelta(training_and_testing_period),
                        model_identifier,
                    )
                )
                model_specs.creation_time = forecast_start
                forecasts, model_state = make_rolling_forecasts(
                    start=forecast_start, end=forecast_end, model_specs=model_specs
                )
                # Upsample to sensor resolution if needed
                if forecasts.index.freq > pd.Timedelta(old_sensor.event_resolution):
                    forecasts = model_specs.outcome_var.resample_data(
                        forecasts,
                        time_window=(forecasts.index.min(), forecasts.index.max()),
                        expected_frequency=old_sensor.event_resolution,
                    )
            except (NotEnoughDataException, MissingData, NaNData) as e:
                click.echo(
                    "Skipping forecasts for old sensor %s: %s" % (old_sensor, str(e))
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

            beliefs = [
                TimedBelief(
                    event_start=ensure_local_timezone(dt, tz_name=LOCAL_TIME_ZONE),
                    belief_horizon=horizon,
                    event_value=value,
                    sensor=old_sensor.corresponding_sensor,
                    source=data_source,
                )
                for dt, value in forecasts.items()
            ]

            print(
                "Saving %s %s-forecasts for %s..."
                % (len(beliefs), naturaldelta(horizon), old_sensor.name)
            )
            for belief in beliefs:
                db.session.add(belief)

    click.echo(
        "DB now has %d forecasts"
        % db.session.query(TimedBelief)
        .filter(TimedBelief.belief_horizon > timedelta(hours=0))
        .count()
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
    sensor_id: Optional[id] = None,
):
    click.echo("Deleting (time series) data from the database %s ..." % db.engine)

    query = db.session.query(TimedBelief).filter(
        TimedBelief.belief_horizon <= timedelta(hours=0)
    )
    if sensor_id is not None:
        query = query.filter(TimedBelief.sensor_id == sensor_id)
    num_measurements_deleted = query.delete()

    click.echo("Deleted %d measurements (ex-post beliefs)" % num_measurements_deleted)


@as_transaction
def depopulate_prognoses(
    db: SQLAlchemy,
    sensor_id: Optional[id] = None,
):
    click.echo(
        "Deleting (time series) forecasts and schedules data from the database %s ..."
        % db.engine
    )

    # Clear all jobs
    num_forecasting_jobs_deleted = app.queues["forecasting"].empty()
    num_scheduling_jobs_deleted = app.queues["scheduling"].empty()

    # Clear all forecasts (data with positive horizon)
    query = db.session.query(TimedBelief).filter(
        TimedBelief.belief_horizon > timedelta(hours=0)
    )
    if sensor_id is not None:
        query = query.filter(TimedBelief.sensor_id == sensor_id)
    num_forecasts_deleted = query.delete()

    click.echo("Deleted %d Forecast Jobs" % num_forecasting_jobs_deleted)
    click.echo("Deleted %d Schedule Jobs" % num_scheduling_jobs_deleted)
    click.echo("Deleted %d forecasts (ex-ante beliefs)" % num_forecasts_deleted)


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
        sequence_names = [s.sequence_name for s in data]
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
            Sensor,
            MarketType,
            Market,
            AssetType,
            Asset,
            WeatherSensorType,
            WeatherSensor,
            DataSource,
        ]
    if data:
        affected_classes += [TimedBelief]
    return affected_classes
