"""
Populate the database with data we know or read in.
"""
import os
from pathlib import Path
from shutil import rmtree
import json
from typing import List
from datetime import datetime, timedelta

from flask import current_app as app
from flask_sqlalchemy import SQLAlchemy
from flask_security.utils import hash_password
import click
import pandas as pd
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.serializer import loads, dumps
from timetomodel.forecasting import make_rolling_forecasts
from timetomodel.exceptions import MissingData, NaNData
from humanize import naturaldelta
import inflect

from bvp.data.models.markets import MarketType, Market, Price
from bvp.data.models.assets import AssetType, Asset, Power
from bvp.data.models.data_sources import DataSource
from bvp.data.models.weather import WeatherSensorType, WeatherSensor, Weather
from bvp.data.models.user import User, Role, RolesUsers
from bvp.data.models.forecasting import lookup_model_specs_configurator
from bvp.data.models.forecasting.exceptions import NotEnoughDataException
from bvp.data.queries.utils import read_sqlalchemy_results
from bvp.data.services.users import create_user
from bvp.utils.time_utils import ensure_korea_local
from bvp.data.transactional import as_transaction


BACKUP_PATH = app.config.get("BVP_DB_BACKUP_PATH")

infl_eng = inflect.engine()


def get_pickle_path() -> str:
    pickle_path = "raw_data/pickles"
    if os.getcwd().endswith("bvp") and "app.py" in os.listdir(os.getcwd()):
        pickle_path = "../" + pickle_path
    if not os.path.exists(pickle_path):
        raise Exception("Could not find %s." % pickle_path)
    if len(os.listdir(pickle_path)) == 0:
        raise Exception("No pickles in %s" % pickle_path)
    return pickle_path


def add_markets(db: SQLAlchemy) -> List[Market]:
    """Add default market types and market(s)"""
    day_ahead = MarketType(
        name="day_ahead",
        display_name="day-ahead market",
        daily_seasonality=True,
        weekly_seasonality=True,
        yearly_seasonality=True,
    )
    db.session.add(day_ahead)
    # db.session.add(MarketType(name="dynamic_tariff", daily_seasonality=True, weekly_seasonality=True,
    #                          yearly_seasonality=True))
    # db.session.add(MarketType(name="fixed_tariff"))
    epex_da = Market(
        name="epex_da",
        market_type=day_ahead,
        unit="EUR/MWh",
        display_name="EPEX SPOT day-ahead market",
    )
    db.session.add(epex_da)
    kpx_da = Market(
        name="kpx_da",
        market_type=day_ahead,
        unit="KRW/kWh",
        display_name="KPX day-ahead market",
    )
    db.session.add(kpx_da)
    return [epex_da, kpx_da]


def add_data_sources(db: SQLAlchemy):
    db.session.add(
        DataSource(
            label="data entered for demonstration purposes", type="script", user_id=None
        )
    )


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
            name="charging_station",
            display_name="Charging station (uni-directional)",
            is_consumer=True,
            can_shift=True,
            daily_seasonality=True,
            weekly_seasonality=True,
            yearly_seasonality=True,
        )
    )
    db.session.add(
        AssetType(
            name="bidirectional_charging_station",
            display_name="Charging station (bi-directional)",
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


def add_sensors(db: SQLAlchemy) -> List[WeatherSensor]:
    """Add default sensor types and sensor(s)"""
    temperature = WeatherSensorType(
        name="temperature", display_name="ambient temperature"
    )
    wind_speed = WeatherSensorType(name="wind_speed", display_name="wind speed")
    radiation = WeatherSensorType(name="radiation", display_name="solar irradiation")
    db.session.add(temperature)
    db.session.add(wind_speed)
    db.session.add(radiation)
    a1_temperature = WeatherSensor(
        name="temperature",
        sensor_type=temperature,
        latitude=33.4843866,
        longitude=126.477859,
        unit="°C",
    )
    db.session.add(a1_temperature)
    a1_wind_speed = WeatherSensor(
        name="wind_speed",
        sensor_type=wind_speed,
        latitude=33.4843866,
        longitude=126.477859,
        unit="m/s",
    )
    db.session.add(a1_wind_speed)
    a1_radiation = WeatherSensor(
        name="total_radiation",
        sensor_type=radiation,
        latitude=33.4843866,
        longitude=126.477859,
        unit="kW/m²",
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
                horizon=timedelta(hours=0),
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
    kpx_market = Market.query.filter_by(name="kpx_da").one_or_none()
    if kpx_market is None:
        raise Exception(
            "Cannot find kpx_da market, which we assume here all assets should belong to."
        )
    assets: List[Asset] = []
    db.session.flush()
    with open(asset_path, "r") as assets_json:
        for json_asset in json.loads(assets_json.read()):
            if "unit" not in json_asset:
                json_asset["unit"] = "MW"
            asset = Asset(**json_asset)
            asset.market_id = kpx_market.id
            test_assets = ["aa-offshore", "hw-onshore", "jc_pv", "jeju_dream_tower"]
            if test_data_set is True and asset.name not in test_assets:
                continue
            assets.append(asset)
            db.session.add(asset)
    assets.append(
        Asset(
            asset_type_name="battery",
            display_name="JoCheon Battery",
            name="jc_bat",
            latitude=33.533744,
            longitude=126.675211 + 0.0002,
            capacity_in_mw=2,
            max_soc_in_mwh=5,
            min_soc_in_mwh=0,
            soc_in_mwh=2.5,
            soc_datetime=ensure_korea_local(datetime(2015, 1, 1, tzinfo=None)),
            unit="MW",
            market_id=kpx_market.id,
        )
    )
    return assets


def add_power(db: SQLAlchemy, assets: List[Asset], test_data_set: bool):
    """
    Adding power measurements from pickles. This is a lot of data points, so we use the bulk method of SQLAlchemy.
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
                horizon=timedelta(hours=0),
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
                horizon=timedelta(hours=0),
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
        check_mx=False,
    )
    create_user(
        username="felix",
        email="felix@seita.nl",
        password=hash_password("testtest"),
        user_roles="admin",
        check_mx=False,
    )
    create_user(
        username="ki_yeol",
        email="shinky@ynu.ac.kr",
        password=hash_password("shadywinter"),
        timezone="Asia/Seoul",
        user_roles="admin",
        check_mx=False,
    )
    create_user(
        username="michael",
        email="michael.kaisers@cwi.nl",
        password=hash_password("shadywinter"),
        user_roles="admin",
        check_mx=False,
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
            check_mx=False,
        )
        for asset in [a for a in assets if a.asset_type_name == asset_type]:
            asset.owner = mock_asset_owner
        # Add batteries to the solar asset owner
        if asset_type == "solar":
            for asset in [a for a in assets if a.asset_type_name == "battery"]:
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
        check_mx=False,
    )

    # anonymous demo user (a Prosumer)
    if app.config.get("BVP_MODE", "") == "demo":
        create_user(
            username="Demo account",
            email="demo@seita.nl",
            password=hash_password("demo"),
            timezone="Asia/Seoul",
            user_roles=[
                "Prosumer",
                dict(
                    name="anonymous", description="An anonymous user cannot make edits."
                ),
            ],
            check_mx=False,
        )


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
def populate_time_series_data(
    db: SQLAlchemy,
    test_data_set: bool,
    generic_asset_type: str = None,
    generic_asset_name: str = None,
):
    click.echo("Populating the database %s with time series data ..." % db.engine)
    if generic_asset_name is None:
        markets = Market.query.all()
    else:
        markets = Market.query.filter(Market.name == generic_asset_name).all()
    if markets:
        add_prices(db, markets, test_data_set)
    else:
        click.echo("No markets in db, so I will not add any prices.")

    if generic_asset_name is None:
        assets = Asset.query.all()
    else:
        assets = Asset.query.filter(Asset.name == generic_asset_name).all()
    if assets:
        add_power(db, assets, test_data_set)
    else:
        click.echo("No assets in db, so I will not add any power measurements.")

    if generic_asset_name is None:
        sensors = WeatherSensor.query.all()
    else:
        sensors = WeatherSensor.query.filter(
            WeatherSensor.name == generic_asset_name
        ).all()
    if sensors:
        add_weather(db, sensors, test_data_set)
    else:
        click.echo("No sensors in db, so I will not add any weather measurements.")

    click.echo("DB now has %d Prices" % db.session.query(Price).count())
    click.echo("DB now has %d Power Measurements" % db.session.query(Power).count())
    click.echo("DB now has %d Weather Measurements" % db.session.query(Weather).count())


@as_transaction  # noqa: C901
def populate_time_series_forecasts(
    db: SQLAlchemy,
    test_data_set: bool,
    generic_asset_type: str = None,
    generic_asset_name: str = None,
    from_date: str = "2015-02-08",
    to_date: str = "2015-12-31",
):
    start = ensure_korea_local(datetime.strptime(from_date, "%Y-%m-%d"))
    end = ensure_korea_local(datetime.strptime(to_date, "%Y-%m-%d") + timedelta(days=1))
    training_and_testing_period = timedelta(days=30)
    horizons = (
        timedelta(hours=1),
        timedelta(hours=6),
        timedelta(hours=24),
        timedelta(hours=48),
    )

    click.echo(
        "Populating the database %s with time series forecasts of %s ahead ..."
        % (db.engine, infl_eng.join([naturaldelta(horizon) for horizon in horizons]))
    )

    # Set a data source for the forecasts
    data_source = DataSource.query.filter(
        DataSource.label == "data entered for demonstration purposes"
    ).one_or_none()

    # List all generic assets for which to forecast.
    # Look into asset type if no asset name is given. If an asset name is given,
    generic_assets = []
    if generic_asset_name is None:
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
                WeatherSensor.name == generic_asset_name
            ).one_or_none()
            if sensors is not None:
                generic_assets.append(sensors)
        if generic_asset_type == "Asset":
            assets = Asset.query.filter(Asset.name == generic_asset_name).one_or_none()
            if assets is not None:
                generic_assets.append(assets)
        if generic_asset_type == "Market":
            markets = Market.query.filter(
                Market.name == generic_asset_name
            ).one_or_none()
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
                        datetime=ensure_korea_local(dt),
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
                        datetime=ensure_korea_local(dt),
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
                        datetime=ensure_korea_local(dt),
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
def depopulate_data(
    db: SQLAlchemy, generic_asset_type: str = None, generic_asset_name: str = None
):
    click.echo("Depopulating (time series) data from the database %s ..." % db.engine)
    num_prices_deleted = 0
    num_power_measurements_deleted = 0
    num_weather_measurements_deleted = 0

    if generic_asset_name is None:
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
                .filter(Market.name == generic_asset_name)
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
                .filter(Asset.name == generic_asset_name)
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
                .filter(WeatherSensor.name == generic_asset_name)
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
def depopulate_forecasts(
    db: SQLAlchemy, generic_asset_type: str = None, generic_asset_name: str = None
):
    click.echo(
        "Depopulating (time series) forecasts data from the database %s ..." % db.engine
    )
    num_prices_deleted = 0
    num_power_measurements_deleted = 0
    num_weather_measurements_deleted = 0

    # Clear all forecasting jobs
    num_jobs_deleted = app.queues["forecasting"].empty()

    # Clear all forecasts (data with positive horizon)
    if generic_asset_name is None:
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
            "Depopulating (time series) forecasts for %s from the database %s ..."
            % (generic_asset_name, db.engine)
        )

        if generic_asset_type == "Market":
            market = (
                db.session.query(Market)
                .filter(Market.name == generic_asset_name)
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
                .filter(Asset.name == generic_asset_name)
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
                .filter(WeatherSensor.name == generic_asset_name)
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
    click.echo("Deleted %d Forecast Jobs" % num_jobs_deleted)
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
        sequence_names = [
            s["sequence_name"]
            for s in read_sqlalchemy_results(
                db.session, "SELECT sequence_name from information_schema.sequences;"
            )
        ]
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


def get_affected_classes(structure: bool = True, data: bool = False):
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
