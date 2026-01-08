from __future__ import annotations

from flask import url_for
from flask_security import current_user
from werkzeug.exceptions import NotFound

from flexmeasures.auth.policy import check_access
from flexmeasures.data import db
from flexmeasures import Asset
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.user import Account
from flexmeasures.ui.utils.view_utils import svg_asset_icon_name


def get_asset_by_id_or_raise_notfound(asset_id: str) -> GenericAsset:
    """find an show existing asset or raise NotFound"""
    if not str(asset_id).isdigit():
        raise NotFound
    asset = db.session.query(GenericAsset).filter_by(id=asset_id).first()
    if asset is None:
        raise NotFound
    return asset


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
        "name": "Add asset",
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
