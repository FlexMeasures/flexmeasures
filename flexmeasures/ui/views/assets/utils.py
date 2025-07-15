from __future__ import annotations
from typing import Optional, Dict

import json
from flask import url_for
from flask_security import current_user
from werkzeug.exceptions import NotFound
from sqlalchemy import select
from sqlalchemy.sql.expression import or_

from flexmeasures.auth.policy import check_access
from flexmeasures.data import db
from flexmeasures import Asset
from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.models.user import Account
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.ui.views.api_wrapper import InternalApi
from flexmeasures.utils.unit_utils import (
    is_energy_price_unit,
    is_energy_unit,
    is_power_unit,
)
from flexmeasures.ui.utils.view_utils import svg_asset_icon_name


def get_asset_by_id_or_raise_notfound(asset_id: str) -> GenericAsset:
    """find an show existing asset or raise NotFound"""
    if not str(asset_id).isdigit():
        raise NotFound
    asset = db.session.query(GenericAsset).filter_by(id=asset_id).first()
    if asset is None:
        raise NotFound
    return asset


def get_allowed_price_sensor_data(account_id: Optional[int]) -> Dict[int, str]:
    """
    Return a list of sensors which the user can add
    as consumption_price_sensor_id or production_price_sensor_id.
    For each sensor we get data as sensor_id: asset_name:sensor_name.

    # todo: this function seem obsolete
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

    # todo: this function seem obsolete
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
                **{"flex_context": json.loads(asset_data.get("flex_context", "{}"))},
                **{
                    "sensors_to_show": json.loads(
                        asset_data.get("sensors_to_show", "[]")
                    )
                },
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


def user_can_create_assets(account: Account | None = None) -> bool:
    if account is None:
        account = current_user.account
    try:
        check_access(account, "create-children")
    except Exception:
        return False
    return True


def user_can_create_children(asset: GenericAsset) -> bool:
    try:
        check_access(asset, "create-children")
    except Exception:
        return False
    return True


def user_can_delete(asset: GenericAsset) -> bool:
    try:
        check_access(asset, "delete")
    except Exception:
        return False
    return True


def user_can_update(asset: GenericAsset) -> bool:
    try:
        check_access(asset, "update")
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


def serialize_asset(asset: Asset, is_head=False) -> dict:
    serialized_asset = {
        "name": asset.name,
        "id": asset.id,
        "asset_type": asset.generic_asset_type.name,
        "link": url_for("AssetCrudUI:get", id=asset.id),
        "icon": svg_asset_icon_name(asset.generic_asset_type.name),
        "tooltip": {
            "name": asset.name,
            "ID": asset.id,
            "Asset Type": asset.generic_asset_type.name,
        },
        "sensors": [
            {
                "name": sensor.name,
                "unit": sensor.unit,
                "link": url_for("SensorUI:get", id=sensor.id),
            }
            for sensor in asset.sensors
        ],
    }

    if asset.parent_asset and not is_head:
        serialized_asset["parent"] = asset.parent_asset.id

    return serialized_asset


def get_list_assets_chart(
    asset: Asset,
    base_asset: Asset,
    parent_depth=0,
    child_depth=0,
    look_for_child=False,
    is_head=False,
) -> list[dict]:
    """
    Recursively builds a tree of assets from a given asset and its parents and children up to a certain depth.

    Args:
        asset: The asset to start the recursion from
        base_asset: The asset that is the base of the chart
        parent_depth: The current depth of the parents hierarchy
        child_depth: The current depth of the children hierarchy
        look_for_child: If True, start looking for children of the current asset
        is_head: If True, the current asset is the head of the chart

    Returns:
        A list of dictionaries representing the assets in the tree
    """
    assets = list()
    asset_def = serialize_asset(asset, is_head=is_head)

    # Fetch parents if there is parent asset and parent_depth is less than 2
    if asset.parent_asset and parent_depth < 2 and not look_for_child:
        parent_depth += 1
        assets += get_list_assets_chart(
            asset=asset.parent_asset,
            base_asset=base_asset,
            parent_depth=parent_depth,
            is_head=False if parent_depth < 2 else True,
        )
    else:
        look_for_child = True
        parent_depth = (
            2  # Auto increase depth in the parents hierarchy is less than two
        )

    assets.append(asset_def)

    if look_for_child and child_depth < 2:
        child_depth += 1
        for child in base_asset.child_assets:
            assets += get_list_assets_chart(
                child,
                parent_depth=parent_depth,
                child_depth=child_depth,
                base_asset=child,
            )

    return assets


def add_child_asset(asset: Asset, assets: list) -> list:
    """
    Add a child asset to the current assets list.
    This function is used to add a child asset to the current asset in the list of assets.
    Args:
        asset: The current asset to be used as parent
        assets: The list of assets
    """
    # Add Extra node to the current asset
    new_child_asset = {
        "name": "Add Child Asset",
        "id": "new",
        "asset_type": asset.generic_asset_type.name,
        "link": url_for("AssetCrudUI:post", id="new", parent_asset_id=asset.id),
        "icon": svg_asset_icon_name("add_asset"),
        "tooltip": "Click here to add a child asset.",
        "sensors": [],
        "parent": asset.id,
    }

    assets.append(new_child_asset)

    return assets
