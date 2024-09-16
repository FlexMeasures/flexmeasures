from __future__ import annotations

import json
from flask import url_for
from flask_security import current_user
from typing import Optional, Dict
from sqlalchemy import select
from sqlalchemy.sql.expression import or_

from flexmeasures.auth.policy import check_access
from flexmeasures.data import db
from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.models.user import Account
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.ui.crud.api_wrapper import InternalApi
from flexmeasures.utils.unit_utils import (
    is_energy_price_unit,
    is_energy_unit,
    is_power_unit,
)


def get_allowed_price_sensor_data(account_id: Optional[int]) -> Dict[int, str]:
    """
    Return a list of sensors which the user can add
    as consumption_price_sensor_id or production_price_sensor_id.
    For each sensor we get data as sensor_id: asset_name:sensor_name.
    """
    if not account_id:
        assets = db.session.scalars(
            select(GenericAsset).filter(GenericAsset.account_id.is_(None))
        ).all()
    else:
        assets = db.session.scalars(
            select(GenericAsset).filter(
                or_(
                    GenericAsset.account_id == account_id,
                    GenericAsset.account_id.is_(None),
                )
            )
        ).all()

    sensors_data = list()
    for asset in assets:
        sensors_data += [
            (sensor.id, asset.name, sensor.name, sensor.unit)
            for sensor in asset.sensors
        ]

    return {
        sensor_id: f"{asset_name}:{sensor_name}"
        for sensor_id, asset_name, sensor_name, sensor_unit in sensors_data
        if is_energy_price_unit(sensor_unit)
    }


def get_allowed_inflexible_sensor_data(account_id: Optional[int]) -> Dict[int, str]:
    """
    Return a list of sensors which the user can add
    as inflexible device sensors.
    This list is built using sensors with energy or power units
    within the current account (or among public assets when account_id argument is not specified).
    For each sensor we get data as sensor_id: asset_name:sensor_name.
    """
    query = None
    if not account_id:
        query = select(GenericAsset).filter(GenericAsset.account_id.is_(None))
    else:
        query = select(GenericAsset).filter(GenericAsset.account_id == account_id)
    assets = db.session.scalars(query).all()

    sensors_data = list()
    for asset in assets:
        sensors_data += [
            (sensor.id, asset.name, sensor.name, sensor.unit)
            for sensor in asset.sensors
        ]

    return {
        sensor_id: f"{asset_name}:{sensor_name}"
        for sensor_id, asset_name, sensor_name, sensor_unit in sensors_data
        if is_energy_unit(sensor_unit) or is_power_unit(sensor_unit)
    }


def process_internal_api_response(
    asset_data: dict, asset_id: int | None = None, make_obj=False
) -> GenericAsset | dict:
    """
    Turn data from the internal API into something we can use to further populate the UI.
    Either as an asset object or a dict for form filling.

    If we add other data by querying the database, we make sure the asset is not in the session afterwards.
    """

    def expunge_asset():
        # use if no insert is wanted from a previous query which flushes its results
        if asset in db.session:
            db.session.expunge(asset)

    asset_data.pop("status", None)  # might have come from requests.response
    if asset_id:
        asset_data["id"] = asset_id
    if make_obj:
        children = asset_data.pop("child_assets", [])

        asset_data.pop("sensors", [])
        asset_data.pop("owner", None)
        asset_type = asset_data.pop("generic_asset_type", {})

        asset = GenericAsset(
            **{
                **asset_data,
                **{"attributes": json.loads(asset_data.get("attributes", "{}"))},
            }
        )  # TODO: use schema?
        if "generic_asset_type_id" in asset_data:
            asset.generic_asset_type = db.session.get(
                GenericAssetType, asset_data["generic_asset_type_id"]
            )
        else:
            asset.generic_asset_type = db.session.get(
                GenericAssetType, asset_type.get("id", None)
            )
        expunge_asset()
        asset.owner = db.session.get(Account, asset_data["account_id"])
        expunge_asset()
        db.session.flush()
        if "id" in asset_data:
            asset.sensors = db.session.scalars(
                select(Sensor).filter_by(generic_asset_id=asset_data["id"])
            ).all()
            expunge_asset()
        if asset_data.get("parent_asset_id", None) is not None:
            asset.parent_asset = db.session.execute(
                select(GenericAsset).filter(
                    GenericAsset.id == asset_data["parent_asset_id"]
                )
            ).scalar_one_or_none()
            expunge_asset()

        child_assets = []
        for child in children:
            if "child_assets" in child:
                # not deeper than one level
                child.pop("child_assets")
            child_asset = process_internal_api_response(child, child["id"], True)
            child_assets.append(child_asset)
        asset.child_assets = child_assets
        expunge_asset()

        return asset
    return asset_data


def user_can_create_assets() -> bool:
    try:
        check_access(current_user.account, "create-children")
    except Exception:
        return False
    return True


def user_can_delete(asset) -> bool:
    try:
        check_access(asset, "delete")
    except Exception:
        return False
    return True


def get_assets_by_account(account_id: int | str | None) -> list[GenericAsset]:
    if account_id is not None:
        get_assets_response = InternalApi().get(
            url_for("AssetAPI:index"), query={"account_id": account_id}
        )
    else:
        get_assets_response = InternalApi().get(url_for("AssetAPI:public"))
    return [
        process_internal_api_response(ad, make_obj=True)
        for ad in get_assets_response.json()
    ]
