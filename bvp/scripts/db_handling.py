"""
Populate the database with data we know or read in.
"""
import os
import json
from typing import List

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_security import SQLAlchemySessionUserDatastore
from flask_security.utils import hash_password
import click

from bvp.models.assets import AssetType, Asset
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
    if os.getcwd().endswith('bvp'):
        asset_path = '../' + asset_path
    if not os.path.exists(asset_path):
        click.echo('Could not find data/assets.json. Exiting ...')
        return []
    assets: List[Asset] = []
    with open(asset_path, 'r') as assets_json:
        for json_asset in json.loads(assets_json.read()):
            asset = Asset(**json_asset)
            assets.append(asset)
            db.session.add(asset)
    return assets


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

    michael = user_datastore.create_user(username="michael",
                                         email='michael.kaisers@cwi.nl',
                                         password=hash_password('shadywinter'))
    user_datastore.add_role_to_user(michael, admin)

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

def populate_structure(app: Flask):
    db = SQLAlchemy(app)
    try:
        add_asset_types(db)
        assets = add_assets(db)
        add_users(db, assets)
        db.session.commit()
    except Exception as e:
        click.echo("[populate_structure] Encountered Problem: %s" % str(e))
        db.session.rollback()
        raise
    click.echo("DB now has %d AssetType objects" % db.session.query(AssetType).count())
    click.echo("DB now has %d Asset objects" % db.session.query(Asset).count())
    click.echo("DB now has %d User objects" % db.session.query(User).count())
    click.echo("DB now has %d Role objects" % db.session.query(Role).count())


def depopulate_structure(app: Flask):
    prompt = "This deletes all asset_type, asset, role and user entries. Do you want to continue?"
    if not click.confirm(prompt):
        return
    db = SQLAlchemy(app)
    try:
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
        click.echo("[depopulate_structure] Encountered Problem: %s" % str(e))
        db.session.rollback()
        raise
    click.echo("Deleted %d AssetType objects" % num_asset_types_deleted)
    click.echo("Deleted %d Asset objects" % num_assets_deleted)
    click.echo("Deleted %d Role objects" % num_roles_deleted)
    click.echo("Deleted %d User objects" % num_users_deleted)


def reset_db(app: Flask):
    db = SQLAlchemy(app)
    db.drop_all()
    db.create_all()
    db.session.commit()
