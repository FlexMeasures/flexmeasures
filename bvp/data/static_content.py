"""
Populate the database with data we know or read in.
"""
import os
import json
from typing import List
from datetime import datetime

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_security import SQLAlchemySessionUserDatastore
from flask_security.utils import hash_password
import click
import pandas as pd

from bvp.data.models.markets import MarketType, Market, Price
from bvp.data.models.assets import AssetType, Asset
from bvp.data.models.measurements import Measurement
from bvp.data.models.user import User, Role


def get_pickle_path() -> str:
    pickle_path = "data/pickles"
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


def add_prices(db: SQLAlchemy, markets:List[Market], test_data_set: bool):
    pickle_path = get_pickle_path()
    db.session.flush()  # make sure markets have IDs
    processed_markets = []
    for market in markets:
        pickle_file = "df_%s_res15T.pickle" % market.name
        pickle_file_path = os.path.join(pickle_path, pickle_file)
        if not os.path.exists(pickle_file_path):
            print(
                "No prices pickle file found in directory to represent %s. Tried '%s'"
                % (market.name, pickle_file_path)
            )
            continue
        df = pd.read_pickle(pickle_file_path)
        print(
            "read in %d records from %s, for Market '%s'"
            % (df.index.size, pickle_file, market.name)
        )
        if market.name in processed_markets:
            raise Exception("We already added prices for the %s market" % market)
        db_market = (
            db.session.query(Market).filter(Market.name == market.name).one_or_none()
        )
        prices = []
        first = None
        count = 0
        for i in range(df.index.size):  # df.iteritems stopped at 10,000 for me (wtf), this is slower than it could be.
            count += 1
            price = df.iloc[i]
            dt = price.name
            value = price.y
            # print("%s: %.2f (%d of %d)" % (dt, value, count, df.index.size))
            if dt < datetime(2015, 1, 1):
                continue  # we only care about 2015 in the static world
            if test_data_set is True and dt >= datetime(2015, 1, 5):
                break
            if dt >= datetime(2015, 3, 29):
                break  # weird problem at 29 March 29, 3am. Let's skip that for the moment. TODO: fix
            if first is None:
                first = dt
            p = Price(datetime=dt, value=value, market_id=db_market.id)
            # p.market = market  # does not work in bulk save
            prices.append(p)
        db.session.bulk_save_objects(prices)
        processed_markets.append(market.name)
        print(
            "Added %d prices for %s (from %s to %s)"
            % (len(prices), market, first, dt)
        )


def add_assets(db: SQLAlchemy, test_data_set: bool) -> List[Asset]:
    """Reads in assets.json. For each asset, create an Asset in the session."""
    asset_path = "data/assets.json"
    if os.getcwd().endswith("bvp") and "app.py" in os.listdir(os.getcwd()):
        asset_path = "../" + asset_path
    if not os.path.exists(asset_path):
        raise Exception("Could not find %s." % asset_path)
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


def add_measurements(db: SQLAlchemy, assets: List[Asset], test_data_set: bool):
    """
    Adding measurements from pickles. This is a lot of data points, so we use the bulk method of SQLAlchemy.

    There is a weird issue with data on March 29, 3am that I couldn't figure out, where a DuplicateKey error is caused.
    """
    pickle_path = get_pickle_path()
    db.session.flush()  # make sure Assets have IDs
    processed_assets = []
    for asset in assets:
        pickle_file = "df_%s_res15T.pickle" % asset.name
        pickle_file_path = os.path.join(pickle_path, pickle_file)
        if not os.path.exists(pickle_file_path):
            print(
                "No measurement pickle file found in directory to represent %s. Tried '%s'"
                % (asset.name, pickle_file_path)
            )
            continue
        df = pd.read_pickle(pickle_file_path)  # .drop_duplicates()
        print(
            "read in %d records from %s, for Asset '%s'"
            % (df.index.size, pickle_file, asset.name)
        )
        if asset.name in processed_assets:
            raise Exception("We already added measurements for %s" % asset)
        db_asset = (
            db.session.query(Asset).filter(Asset.name == asset.name).one_or_none()
        )
        measurements = []
        first = None
        count = 0
        for dt in df.index:
            count += 1
            count += 1
            value = df.loc[dt]["y"]
            # print("%s: %.2f (%d of %d)" % (dt, value, count, df.index.size))
            if test_data_set is True and dt >= datetime(2015, 1, 5):
                break
            if dt >= datetime(2015, 3, 29):
                break  # weird problem at 29 March 29, 3am. Let's skip that for the moment. TODO: fix
            if first is None:
                first = dt
            m = Measurement(datetime=dt, value=value, asset_id=db_asset.id)
            # m.asset = asset  # does not work in bulk save
            measurements.append(m)
        db.session.bulk_save_objects(measurements)
        processed_assets.append(asset.name)
        print(
            "Added %d measurements for %s (from %s to %s)"
            % (len(measurements), asset, first, dt)
        )


def add_users(db: SQLAlchemy, assets: List[Asset]):
    # print(bcrypt.gensalt())  # I used this to generate a salt value for my PASSWORD_SALT env
    user_datastore = SQLAlchemySessionUserDatastore(db.session, User, Role)

    # Admins
    admin = user_datastore.create_role(
        name="admin", description="An admin has access to all assets and controls."
    )
    nicolas = user_datastore.create_user(
        username="nicolas",
        email="iam@nicolashoening.de",
        password=hash_password("testtest"),
    )
    user_datastore.add_role_to_user(nicolas, admin)
    felix = user_datastore.create_user(
        username="felix", email="felix@seita.nl", password=hash_password("testtest")
    )
    user_datastore.add_role_to_user(felix, admin)
    ki_yeol = user_datastore.create_user(
        username="ki_yeol",
        email="shinky@ynu.ac.kr",
        password=hash_password("shadywinter"),
        timezone="Asia/Seoul",
    )
    user_datastore.add_role_to_user(ki_yeol, admin)

    michael = user_datastore.create_user(
        username="michael",
        email="michael.kaisers@cwi.nl",
        password=hash_password("shadywinter"),
    )
    user_datastore.add_role_to_user(michael, admin)

    # Asset owners
    asset_owner = user_datastore.create_role(
        name="asset-owner",
        description="An asset owner can has access to a subset of assets.",
    )
    for asset_type in ("solar", "wind", "charging_station", "building"):
        mock_asset_owner = user_datastore.create_user(
            username="mocked %s-owner" % asset_type,
            email="%s@seita.nl" % asset_type,
            password=hash_password(asset_type),
            timezone="Asia/Seoul",
        )
        user_datastore.add_role_to_user(mock_asset_owner, asset_owner)
        for asset in [a for a in assets if a.asset_type_name == asset_type]:
            asset.owner = mock_asset_owner


# ------------ Main functions --------------------------------
# These could be registered at the app object as cli functions


def populate(app: Flask, measurements: bool, test_data_set: bool):
    db = SQLAlchemy(app)
    try:
        markets = add_markets(db)
        add_prices(db, markets, test_data_set)
        add_asset_types(db)
        assets = add_assets(db, test_data_set)
        add_users(db, assets)
        db.session.commit()  # extra session commit before adding all the measurements
        if measurements:
            add_measurements(db, assets, test_data_set)
        db.session.commit()
    except Exception as e:
        click.echo("[db_populate] Encountered Problem: %s" % str(e))
        db.session.rollback()
        raise
    click.echo("DB now has %d MarketTypes" % db.session.query(MarketType).count())
    click.echo("DB now has %d Markets" % db.session.query(Market).count())
    click.echo("DB now has %d Prices" % db.session.query(Price).count())
    click.echo("DB now has %d AssetTypes" % db.session.query(AssetType).count())
    click.echo("DB now has %d Assets" % db.session.query(Asset).count())
    if measurements:
        click.echo(
            "DB now has %d Measurements" % db.session.query(Measurement).count()
        )
    click.echo("DB now has %d Users" % db.session.query(User).count())
    click.echo("DB now has %d Roles" % db.session.query(Role).count())


def depopulate(app: Flask, force: bool):
    if not force:
        prompt = "This deletes all market_types, markets, asset_type, asset, measurement, role and user entries. "\
                 "Do you want to continue?"
        if not click.confirm(prompt):
            return
    db = SQLAlchemy(app)
    try:
        num_prices_deleted = db.session.query(Price).delete()
        num_markets_deleted = db.session.query(Market).delete()
        num_market_types_deleted = db.session.query(MarketType).delete()
        num_measurements_deleted = db.session.query(Measurement).delete()
        num_assets_deleted = db.session.query(Asset).delete()
        num_asset_types_deleted = db.session.query(AssetType).delete()
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
        db.session.commit()
    except Exception as e:
        click.echo("[db_depopulate] Encountered Problem: %s" % str(e))
        db.session.rollback()
        raise
    click.echo("Deleted %d MarketTypes" % num_market_types_deleted)
    click.echo("Deleted %d Markets" % num_markets_deleted)
    click.echo("Deleted %d Prices" % num_prices_deleted)
    click.echo("Deleted %d AssetTypes" % num_asset_types_deleted)
    click.echo("Deleted %d Assets" % num_assets_deleted)
    click.echo("Deleted %d Measurements" % num_measurements_deleted)
    click.echo("Deleted %d Roles" % num_roles_deleted)
    click.echo("Deleted %d Users" % num_users_deleted)


def reset_db(app: Flask):
    db = SQLAlchemy(app)
    db.drop_all()
    db.create_all()
    db.session.commit()
