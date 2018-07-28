"""
Populate the database with data we know or read in.
"""
import os
import json
from typing import List
from datetime import datetime, timedelta

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_security.utils import hash_password
import click
import pandas as pd
from sqlalchemy.sql import or_
from isodate import parse_duration
from ts_forecasting_pipeline.forecasting import make_rolling_forecasts

from bvp.data.models.markets import MarketType, Market, Price
from bvp.data.models.assets import AssetType, Asset, Power
from bvp.data.models.data_sources import DataSource
from bvp.data.models.weather import WeatherSensorType, WeatherSensor, Weather
from bvp.data.models.user import User, Role
from bvp.data.models.forecasting.solar import latest as solar_latest
from bvp.data.services.users import create_user
from bvp.utils.time_utils import as_bvp_time


def get_pickle_path() -> str:
    pickle_path = "raw_data/pickles"
    if os.getcwd().endswith("bvp") and "app.py" in os.listdir(os.getcwd()):
        pickle_path = "../" + pickle_path
    if not os.path.exists(pickle_path):
        raise Exception("Could not find %s." % pickle_path)
    if len(os.listdir(pickle_path)) == 0:
        raise Exception("No pickles in %s" % pickle_path)
    return pickle_path


def ensure_korea_local(dt: pd.Timestamp) -> pd.Timestamp:
    if dt.tzinfo is not None:
        return dt.tz_convert("Asia/Seoul")
    else:
        return dt.tz_localize("Asia/Seoul")


def add_markets(db: SQLAlchemy) -> List[Market]:
    """Add default market types and market(s)"""
    day_ahead = MarketType(
        name="day_ahead",
        daily_seasonality=True,
        weekly_seasonality=True,
        yearly_seasonality=True,
    )
    db.session.add(day_ahead)
    # db.session.add(MarketType(name="dynamic_tariff", daily_seasonality=True, weekly_seasonality=True,
    #                          yearly_seasonality=True))
    # db.session.add(MarketType(name="fixed_tariff"))
    epex_da = Market(name="epex_da", market_type=day_ahead)
    db.session.add(epex_da)
    return [epex_da]


def add_user_data_sources(db: SQLAlchemy):
    """Register all users as potential data sources."""
    users = db.session.query(
        User
    ).all()  # Todo: only add a data_source if the user is not already registered as a data source
    for user in users:
        db.session.add(
            DataSource(
                label="data entered by user %s" % user.username,
                type="user",
                user_id=user.id,
            )
        )


def add_data_sources(db: SQLAlchemy):
    db.session.add(
        DataSource(
            label="data entered for demonstration purposes", type="script", user_id=None
        )
    )
    add_user_data_sources(db)


def add_asset_types(db: SQLAlchemy):
    db.session.add(
        AssetType(
            name="solar",
            is_producer=True,
            daily_seasonality=True,
            yearly_seasonality=True,
        )
    )
    db.session.add(
        AssetType(
            name="wind",
            is_producer=True,
            can_curtail=True,
            daily_seasonality=True,
            yearly_seasonality=True,
        )
    )
    db.session.add(
        AssetType(
            name="charging_station",
            is_consumer=True,
            can_shift=True,
            daily_seasonality=True,
            weekly_seasonality=True,
            yearly_seasonality=True,
        )
    )
    db.session.add(
        AssetType(
            name="battery",
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
            is_consumer=True,
            can_shift=True,
            daily_seasonality=True,
            weekly_seasonality=True,
            yearly_seasonality=True,
        )
    )


def add_sensors(db: SQLAlchemy) -> List[WeatherSensor]:
    """Add default sensor types and sensor(s)"""
    temperature = WeatherSensorType(name="temperature")
    wind_speed = WeatherSensorType(name="wind_speed")
    radiation = WeatherSensorType(name="radiation")
    db.session.add(temperature)
    db.session.add(wind_speed)
    db.session.add(radiation)
    a1_temperature = WeatherSensor(
        name="temperature",
        sensor_type=temperature,
        latitude=33.4843866,
        longitude=126.477859,
    )
    db.session.add(a1_temperature)
    a1_wind_speed = WeatherSensor(
        name="wind_speed",
        sensor_type=wind_speed,
        latitude=33.4843866,
        longitude=126.477859,
    )
    db.session.add(a1_wind_speed)
    a1_radiation = WeatherSensor(
        name="total_radiation",
        sensor_type=radiation,
        latitude=33.4843866,
        longitude=126.477859,
    )
    db.session.add(a1_radiation)
    return [a1_temperature, a1_wind_speed, a1_radiation]


def add_prices(db: SQLAlchemy, markets: List[Market], test_data_set: bool):
    pickle_path = get_pickle_path()
    processed_markets = []
    data_source = DataSource.query.filter(
        DataSource.label == "data entered for demonstration purposes"
    ).one_or_none()
    for market in markets:
        pickle_file = "df_%s_res15T.pickle" % market.name
        pickle_file_path = os.path.join(pickle_path, pickle_file)
        if not os.path.exists(pickle_file_path):
            click.echo(
                "No prices pickle file found in directory to represent %s. Tried '%s'"
                % (market.name, pickle_file_path)
            )
            continue
        df = pd.read_pickle(pickle_file_path)
        click.echo(
            "read in %d records from %s, for Market '%s'"
            % (df.index.size, pickle_file, market.name)
        )
        if market.name in processed_markets:
            raise Exception("We already added prices for the %s market" % market)
        prices = []
        first = None
        last = None
        count = 0
        for i in range(
            df.index.size
        ):  # df.iteritems stopped at 10,000 for me (wtf), this is slower than it could be.
            price_row = df.iloc[i]
            dt = ensure_korea_local(price_row.name)
            value = price_row.y
            if dt < datetime(2015, 1, 1, tzinfo=dt.tz):
                continue  # we only care about 2015 in the static world
            if test_data_set is True and dt >= datetime(2015, 1, 5, tzinfo=dt.tz):
                break
            count += 1
            # click.echo("%s: %.2f (%d of %d)" % (dt, value, count, df.index.size))
            last = dt
            if first is None:
                first = dt
            p = Price(
                datetime=dt,
                horizon=parse_duration("-PT15M"),
                value=value,
                market_id=market.id,
                data_source_id=data_source.id,
            )
            # p.market = market  # does not work in bulk save
            prices.append(p)
        db.session.bulk_save_objects(prices)
        processed_markets.append(market.name)
        click.echo(
            "Added %d prices for %s (from %s to %s)"
            % (len(prices), market, first, last)
        )


def add_assets(db: SQLAlchemy, test_data_set: bool) -> List[Asset]:
    """Reads in assets.json. For each asset, create an Asset in the session."""
    asset_path = "raw_data/assets.json"
    if os.getcwd().endswith("bvp") and "app.py" in os.listdir(os.getcwd()):
        asset_path = "../" + asset_path
    if not os.path.exists(asset_path):
        raise Exception("Could not find %s/%s." % (os.getcwd(), asset_path))
    assets: List[Asset] = []
    with open(asset_path, "r") as assets_json:
        for json_asset in json.loads(assets_json.read()):
            asset = Asset(**json_asset)
            test_assets = ["aa-offshore", "hw-onshore", "jc_pv", "jeju_dream_tower"]
            if test_data_set is True and asset.name not in test_assets:
                continue
            assets.append(asset)
            db.session.add(asset)
    return assets


def add_power(db: SQLAlchemy, assets: List[Asset], test_data_set: bool):
    """
    Adding power measurements from pickles. This is a lot of data points, so we use the bulk method of SQLAlchemy.

    There is a weird issue with data on March 29, 3am that I couldn't figure out, where a DuplicateKey error is caused.
    """
    pickle_path = get_pickle_path()
    processed_assets = []
    data_source = DataSource.query.filter(
        DataSource.label == "data entered for demonstration purposes"
    ).one_or_none()
    for asset in assets:
        pickle_file = "df_%s_res15T.pickle" % asset.name
        pickle_file_path = os.path.join(pickle_path, pickle_file)
        if not os.path.exists(pickle_file_path):
            click.echo(
                "No power measurement pickle file found in directory to represent %s. Tried '%s'"
                % (asset.name, pickle_file_path)
            )
            continue
        df = pd.read_pickle(pickle_file_path)
        click.echo(
            "read in %d records from %s, for Asset '%s'"
            % (df.index.size, pickle_file, asset.name)
        )
        if asset.name in processed_assets:
            raise Exception("We already added power measurements for %s" % asset)
        power_measurements = []
        first = None
        last = None
        count = 0
        for i in range(
            df.index.size
        ):  # df.iteritems stopped at 10,000 for me (wtf), this is slower than it could be.
            power_row = df.iloc[i]
            dt = ensure_korea_local(power_row.name)
            value = power_row.y
            if test_data_set is True and dt >= datetime(2015, 1, 5, tzinfo=dt.tz):
                break
            count += 1
            # click.echo("%s: %.2f (%d of %d)" % (dt, value, count, df.index.size))
            last = dt
            if first is None:
                first = dt
            p = Power(
                datetime=dt,
                horizon=parse_duration("-PT15M"),
                value=value,
                asset_id=asset.id,
                data_source_id=data_source.id,
            )
            # p.asset = asset  # does not work in bulk save
            power_measurements.append(p)
        db.session.bulk_save_objects(power_measurements)
        processed_assets.append(asset.name)
        click.echo(
            "Added %d power measurements for %s (from %s to %s)"
            % (len(power_measurements), asset, first, last)
        )


def add_weather(db: SQLAlchemy, sensors: List[WeatherSensor], test_data_set: bool):
    """
    Adding weather measurements from pickles. This is a lot of data points, so we use the bulk method of SQLAlchemy.

    There is a weird issue with data on March 29, 3am that I couldn't figure out, where a DuplicateKey error is caused.
    """
    pickle_path = get_pickle_path()
    processed_sensors = []
    data_source = DataSource.query.filter(
        DataSource.label == "data entered for demonstration purposes"
    ).one_or_none()
    for sensor in sensors:
        pickle_file = "df_%s_res15T.pickle" % sensor.name
        pickle_file_path = os.path.join(pickle_path, pickle_file)
        if not os.path.exists(pickle_file_path):
            click.echo(
                "No weather measurement pickle file found in directory to represent %s. Tried '%s'"
                % (sensor.name, pickle_file_path)
            )
            continue
        df = pd.read_pickle(pickle_file_path)  # .drop_duplicates()
        click.echo(
            "read in %d records from %s, for Asset '%s'"
            % (df.index.size, pickle_file, sensor.name)
        )
        if sensor.name in processed_sensors:
            raise Exception("We already added weather measurements for %s" % sensor)
        weather_measurements = []
        first = None
        last = None
        count = 0
        for i in range(
            df.index.size
        ):  # df.iteritems stopped at 10,000 for me (wtf), this is slower than it could be.
            weather_row = df.iloc[i]
            dt = ensure_korea_local(weather_row.name)
            value = weather_row.y
            if test_data_set is True and dt >= datetime(2015, 1, 5, tzinfo=dt.tz):
                break
            count += 1
            # click.echo("%s: %.2f (%d of %d)" % (dt, value, count, df.index.size))
            last = dt
            if first is None:
                first = dt
            w = Weather(
                datetime=dt,
                horizon=parse_duration("-PT15M"),
                value=value,
                sensor_id=sensor.id,
                data_source_id=data_source.id,
            )
            # w.sensor = sensor  # does not work in bulk save
            weather_measurements.append(w)

        db.session.bulk_save_objects(weather_measurements)
        processed_sensors.append(sensor.name)
        click.echo(
            "Added %d weather measurements for %s (from %s to %s)"
            % (len(weather_measurements), sensor, first, last)
        )


def add_users(db: SQLAlchemy, assets: List[Asset]):
    # click.echo(bcrypt.gensalt())  # I used this to generate a salt value for my PASSWORD_SALT env

    # Admins
    create_user(
        username="nicolas",
        email="iam@nicolashoening.de",
        password=hash_password("testtest"),
        user_roles=dict(
            name="admin", description="An admin has access to all assets and controls."
        ),
    )
    create_user(
        username="felix",
        email="felix@seita.nl",
        password=hash_password("testtest"),
        user_roles="admin",
    )
    create_user(
        username="ki_yeol",
        email="shinky@ynu.ac.kr",
        password=hash_password("shadywinter"),
        timezone="Asia/Seoul",
        user_roles="admin",
    )
    create_user(
        username="michael",
        email="michael.kaisers@cwi.nl",
        password=hash_password("shadywinter"),
        user_roles="admin",
    )

    # Asset owners
    for asset_type in ("solar", "wind", "charging_station", "building"):
        mock_asset_owner = create_user(
            username="mocked %s-owner" % asset_type,
            email="%s@seita.nl" % asset_type,
            password=hash_password(asset_type),
            timezone="Asia/Seoul",
            user_roles=dict(
                name="Prosumer", description="USEF defined role of asset owner."
            ),
        )
        assert mock_asset_owner not in db.session
        mock_asset_owner = db.session.merge(mock_asset_owner)
        for asset in [a for a in assets if a.asset_type_name == asset_type]:
            asset.owner = mock_asset_owner

    # task runner
    create_user(
        username="Tasker",
        email="tasker@seita.nl",
        password=hash_password("take-a-coleslaw"),
        timezone="Europe/Amsterdam",
        user_roles=dict(
            name="task-runner", description="Process running BVP-relevant tasks."
        ),
    )


def as_transaction(db_function):
    """Decorator for handling SQLAlchemy commands as a database transaction (ACID).
    Calls db operation function and when it is done, submits the db session.
    Rolls back the session if anything goes wrong."""

    def wrap(app: Flask, *args, **kwargs):
        db = SQLAlchemy(app)
        try:
            db_function(db, *args, **kwargs)
            db.session.commit()
        except Exception as e:
            click.echo("[%s] Encountered Problem: %s" % (db_function.__name__, str(e)))
            db.session.rollback()
            raise
        finally:
            db.session.close()

    return wrap


# ------------ Main functions --------------------------------
# These can registered at the app object as cli functions


@as_transaction
def populate_structure(db: SQLAlchemy, test_data_set: bool):
    """
    Add all meta data for assets, markets, users
    """
    click.echo("Populating the database %s with structural data ..." % db.engine)
    add_markets(db)
    add_asset_types(db)
    assets = add_assets(db, test_data_set)
    add_sensors(db)
    add_users(db, assets)
    add_data_sources(db)
    click.echo("DB now has %d MarketTypes" % db.session.query(MarketType).count())
    click.echo("DB now has %d Markets" % db.session.query(Market).count())
    click.echo("DB now has %d AssetTypes" % db.session.query(AssetType).count())
    click.echo("DB now has %d Assets" % db.session.query(Asset).count())
    click.echo(
        "DB now has %d WeatherSensorTypes" % db.session.query(WeatherSensorType).count()
    )
    click.echo("DB now has %d WeatherSensors" % db.session.query(WeatherSensor).count())
    click.echo("DB now has %d DataSources" % db.session.query(DataSource).count())
    click.echo("DB now has %d Users" % db.session.query(User).count())
    click.echo("DB now has %d Roles" % db.session.query(Role).count())


@as_transaction
def populate_time_series_data(db: SQLAlchemy, test_data_set: bool):
    click.echo("Populating the database %s with time series data ..." % db.engine)
    markets = Market.query.all()
    if markets:
        add_prices(db, markets, test_data_set)
    else:
        click.echo("No markets in db, so I will not add any prices.")

    assets = Asset.query.all()
    if assets:
        add_power(db, assets, test_data_set)
    else:
        click.echo("No assets in db, so I will not add any power measurements.")

    sensors = WeatherSensor.query.all()
    if sensors:
        add_weather(db, sensors, test_data_set)
    else:
        click.echo("No sensors in db, so I will not add any weather measurements.")

    click.echo("DB now has %d Prices" % db.session.query(Price).count())
    click.echo("DB now has %d Power Measurements" % db.session.query(Power).count())
    click.echo("DB now has %d Weather Measurements" % db.session.query(Weather).count())


@as_transaction
def populate_time_series_forecasts(db: SQLAlchemy, test_data_set: bool):
    click.echo(
        "Populating the database %s with time series forecasts (48H) ..." % db.engine
    )

    start = as_bvp_time(datetime(2015, 2, 8))
    end = as_bvp_time(datetime(2015, 12, 31, 23, 45))

    data_source = DataSource.query.filter(
        DataSource.label == "data entered for demonstration purposes"
    ).one_or_none()
    """
    assets = Asset.query.filter(
        or_(
            Asset.asset_type_name == "solar",
            Asset.asset_type_name == "wind",
            Asset.asset_type_name == "building",
            Asset.asset_type_name == "charging_station",
            Asset.asset_type_name == "battery",
        )
    ).all()
    """
    assets = Asset.query.filter(
        or_(
            Asset.asset_type_name == "solar",
            Asset.asset_type_name == "building",
            Asset.asset_type_name == "wind",
        )
    ).all()
    for asset in assets:
        print(
            "Computing forecasts for %s, train model with data from %s to %s ..."
            % (asset.name, start, end)
        )
        model_specs = solar_latest(
            solar_asset=asset,
            start_of_training=start - timedelta(days=30),
            end_of_testing=start - timedelta(minutes=15),
            query_until=end,
            specs_only=True,
        )
        model_specs.creation_time = start
        forecasts, model_state = make_rolling_forecasts(
            start=start,
            end=end,
            training_period=timedelta(days=30),
            model_specs=model_specs,
        )

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

        power_forecasts = [
            Power(
                datetime=ensure_korea_local(dt),
                horizon=parse_duration("PT48H"),
                value=value,
                asset_id=asset.id,
                data_source_id=data_source.id,
            )
            for dt, value in forecasts.items()
        ]

        db.session.bulk_save_objects(power_forecasts)

    else:
        click.echo("No assets in db, so I will not add any power forecasts.")

    click.echo("DB now has %d Power Forecasts" % db.session.query(Power).count())


@as_transaction
def depopulate_structure(db: SQLAlchemy):
    click.echo("Depopulating structural data from the database %s ..." % db.engine)
    num_markets_deleted = db.session.query(Market).delete()
    num_market_types_deleted = db.session.query(MarketType).delete()
    num_assets_deleted = db.session.query(Asset).delete()
    num_asset_types_deleted = db.session.query(AssetType).delete()
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
def depopulate_data(db: SQLAlchemy):
    click.echo("Depopulating (time series) data from the database %s ..." % db.engine)
    num_prices_deleted = db.session.query(Price).filter_by(horizon="PT0M").delete()
    num_power_measurements_deleted = (
        db.session.query(Power).filter_by(horizon=parse_duration("-PT15M")).delete()
    )
    num_weather_measurements_deleted = (
        db.session.query(Weather).filter_by(horizon=parse_duration("-PT15M")).delete()
    )
    click.echo("Deleted %d Prices" % num_prices_deleted)
    click.echo("Deleted %d Power Measurements" % num_power_measurements_deleted)
    click.echo("Deleted %d Weather Measurements" % num_weather_measurements_deleted)


@as_transaction
def depopulate_forecasts(db: SQLAlchemy):
    click.echo(
        "Depopulating (time series) forecasts from the database %s ..." % db.engine
    )
    num_prices_deleted = (
        db.session.query(Price)
        .filter(Price.horizon != parse_duration("-PT15M"))
        .delete()
    )
    num_power_measurements_deleted = (
        db.session.query(Power)
        .filter(Power.horizon != parse_duration("-PT15M"))
        .delete()
    )
    num_weather_measurements_deleted = (
        db.session.query(Weather)
        .filter(Weather.horizon != parse_duration("-PT15M"))
        .delete()
    )
    click.echo("Deleted %d Price Forecasts" % num_prices_deleted)
    click.echo("Deleted %d Power Forecasts" % num_power_measurements_deleted)
    click.echo("Deleted %d Weather Forecasts" % num_weather_measurements_deleted)


def reset_db(app: Flask):
    db = SQLAlchemy(app)
    db.session.commit()  # close any existing sessions
    click.echo("Dropping everything in %s ..." % db.engine)
    db.reflect()  # see http://jrheard.tumblr.com/post/12759432733/dropping-all-tables-on-postgres-using
    db.drop_all()
    click.echo("Recreating everything ...")
    db.create_all()
    click.echo("Committing ...")
    db.session.commit()
