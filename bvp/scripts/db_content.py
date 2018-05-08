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

from bvp.models.assets import AssetType, Asset
from bvp.models.measurements import Measurement
from bvp.models.user import User, Role


def add_asset_types(db: SQLAlchemy):
    db.session.add(AssetType(name="solar", is_producer=True, daily_seasonality=True, yearly_seasonality=True))
    db.session.add(AssetType(name="wind", is_producer=True, can_curtail=True, daily_seasonality=True,
                             yearly_seasonality=True))
    db.session.add(AssetType(name="charging_station", is_consumer=True, can_shift=True,
                             daily_seasonality=True, weekly_seasonality=True, yearly_seasonality=True))
    db.session.add(AssetType(name="battery", is_consumer=True, is_producer=True, can_curtail=True, can_shift=True,
                             daily_seasonality=True, weekly_seasonality=True, yearly_seasonality=True))
    db.session.add(AssetType(name="building", is_consumer=True, can_shift=True,
                             daily_seasonality=True, weekly_seasonality=True, yearly_seasonality=True))


def add_assets(db: SQLAlchemy) -> List[Asset]:
    """Reads in assets.json. For each asset, create an Asset in the session."""
    asset_path = 'data/assets.json'
    if os.getcwd().endswith('bvp') and 'app.py' in os.listdir(os.getcwd()):
        asset_path = '../' + asset_path
    if not os.path.exists(asset_path):
        raise Exception('Could not find %s.' % asset_path)
    assets: List[Asset] = []
    with open(asset_path, 'r') as assets_json:
        for json_asset in json.loads(assets_json.read()):
            asset = Asset(**json_asset)
            assets.append(asset)
            db.session.add(asset)
    return assets


def add_measurements(db: SQLAlchemy):
    """
    Adding measurements from pickles. This is a lot of data points, so we use the bulk method of SQLAlchemy.

    There is a weird issue with data on March 29, 3am that I couldn't figure out, where a DuplicateKey error is caused.
    """
    pickle_path = 'data/pickles'
    if os.getcwd().endswith('bvp') and 'app.py' in os.listdir(os.getcwd()):
        pickle_path = '../' + pickle_path
    if not os.path.exists(pickle_path):
        raise Exception('Could not find %s.' % pickle_path)
    if len(os.listdir(pickle_path)) == 0:
        raise Exception("No pickles in %s" % pickle_path)

    db.session.flush()  # make sure Assets have IDs
    assets = db.session.query(Asset).all()

    processed_assets = []
    for pckl in [pckl_file for pckl_file in os.listdir(pickle_path) if pckl_file.endswith(".pickle")]:
        df = pd.read_pickle(os.path.join(pickle_path, pckl))
        asset_name = pckl[3:].split("_res15T")[0]
        print("read in %d records from %s, for Asset '%s'" % (df.index.size, pckl, asset_name))
        assets_with_name = [a for a in assets if a.name == asset_name]
        if len(assets_with_name) == 0:
            print("No asset found in DB to represent %s." % os.path.join(pickle_path, pckl))
            continue
        asset = assets_with_name[0]
        if asset.name in processed_assets:
            raise Exception("We already added measurements for %s" % asset)
        measurements = []
        first = None
        for dt in df.index:
            if first is None:
                first = dt
            if dt >= datetime(2015, 3, 29):
                break  # weird problem at 29 March 29, 3am. Let's skip that for the moment. TODO: fix
            m = Measurement(datetime=dt, value=df.loc[dt]["y"], asset_id=asset.id)
            # m.asset = asset  # does not work in bulk save
            measurements.append(m)
        db.session.bulk_save_objects(measurements)
        processed_assets.append(asset.name)
        print("Added %d measurements for %s (from %s to %s)" % (len(measurements), asset, first, dt))


def add_users(db: SQLAlchemy, assets: List[Asset]):
    # print(bcrypt.gensalt())  # I used this to generate a salt value for my PASSWORD_SALT env
    user_datastore = SQLAlchemySessionUserDatastore(db.session, User, Role)

    # Admins
    admin = user_datastore.create_role(name="admin", description="An admin has access to all assets and controls.")
    nicolas = user_datastore.create_user(username="nicolas",
                                         email='iam@nicolashoening.de',
                                         password=hash_password('testtest'))
    user_datastore.add_role_to_user(nicolas, admin)
    felix = user_datastore.create_user(username="felix",
                                       email='felix@seita.nl',
                                       password=hash_password('testtest'))
    user_datastore.add_role_to_user(felix, admin)
    ki_yeol = user_datastore.create_user(username="ki_yeol",
                                         email='shinky@ynu.ac.kr',
                                         password=hash_password('shadywinter'),
                                         timezone="Asia/Seoul")
    user_datastore.add_role_to_user(ki_yeol, admin)

    # Asset owners
    asset_owner = user_datastore.create_role(name="asset-owner",
                                             description="An asset owner can has access to a subset of assets.")
    for asset_type in ("solar", "wind", "charging_station", "building"):
        mock_asset_owner = user_datastore.create_user(username="mocked %s-owner" % asset_type,
                                                      email='%s@seita.nl' % asset_type,
                                                      password=hash_password(asset_type),
                                                      timezone="Asia/Seoul")
        user_datastore.add_role_to_user(mock_asset_owner, asset_owner)
        for asset in [a for a in assets if a.asset_type_name == asset_type]:
            asset.owner = mock_asset_owner


# ------------ Main functions --------------------------------
# These could be registered at the app object as cli functions

def populate(app: Flask, measurements: bool):
    db = SQLAlchemy(app)
    try:
        add_asset_types(db)
        assets = add_assets(db)
        if measurements is True:
            add_measurements(db)
        add_users(db, assets)
        db.session.commit()
    except Exception as e:
        click.echo("[db_populate] Encountered Problem: %s" % str(e))
        db.session.rollback()
        raise
    click.echo("DB now has %d AssetType objects" % db.session.query(AssetType).count())
    click.echo("DB now has %d Asset objects" % db.session.query(Asset).count())
    click.echo("DB now has %d Measurement objects" % db.session.query(Measurement).count())
    click.echo("DB now has %d User objects" % db.session.query(User).count())
    click.echo("DB now has %d Role objects" % db.session.query(Role).count())


def depopulate(app: Flask, force: bool, measurements: bool):
    if force is False:
        prompt = "This deletes all asset_type, asset, measurement, role and user entries. Do you want to continue?"
        if not click.confirm(prompt):
            return
    db = SQLAlchemy(app)
    try:
        num_assets_deleted = db.session.query(Asset).delete()
        num_asset_types_deleted = db.session.query(AssetType).delete()
        if measurements:
            num_measurements_deleted = db.session.query(Measurement).delete()
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
    click.echo("Deleted %d AssetType objects" % num_asset_types_deleted)
    click.echo("Deleted %d Asset objects" % num_assets_deleted)
    if measurements:
        click.echo("Deleted %d Measurement objects" % num_measurements_deleted)
    click.echo("Deleted %d Role objects" % num_roles_deleted)
    click.echo("Deleted %d User objects" % num_users_deleted)


def reset_db(app: Flask):
    db = SQLAlchemy(app)
    db.drop_all()
    db.create_all()
    db.session.commit()
