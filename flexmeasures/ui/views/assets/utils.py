from __future__ import annotations

from flask import url_for
from markupsafe import Markup
from werkzeug.exceptions import NotFound

from flexmeasures import Asset
from flexmeasures.data import db
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.schemas.sensors import unset_sensor_reference_paths
from flexmeasures.ui.utils.auth_utils import user_can_access
from flexmeasures.ui.utils.breadcrumb_utils import (
    ANOTHER_ORGANISATION,
    viewer_may_read,
)
from flexmeasures.ui.utils.view_utils import svg_asset_icon_name


def get_asset_by_id_or_raise_notfound(asset_id: str) -> GenericAsset:
    """find an show existing asset or raise NotFound"""
    if not str(asset_id).isdigit():
        raise NotFound
    asset = db.session.get(GenericAsset, int(asset_id))
    if asset is None:
        raise NotFound
    return asset


def get_inherited_flex_context(asset: GenericAsset) -> dict[str, dict]:
    """Collect the flex-context fields the asset would inherit from its ancestors.

    Fields set on the asset itself are not excluded here:
    the flex-context editor decides at render time which of these are shadowed by local fields,
    so that removing a local field immediately reveals the inherited value it was shadowing.

    :returns: Dictionary mapping each ancestor-defined field name to a dictionary with
              the field's ``value`` and the ``asset_id`` and ``asset_name`` of the defining ancestor.

    Values set on an ancestor the viewer may not read (in another organisation) are left out,
    with ``hidden`` set, so the page can say a value is inherited without showing it.
    Scheduling still uses them.
    """
    if asset.parent_asset is None:
        return {}
    inherited = {}
    readable: dict[int, bool] = {}
    for field, entry in asset.parent_asset.get_flex_context_with_provenance().items():
        ancestor = entry["asset"]
        if ancestor.id not in readable:
            readable[ancestor.id] = viewer_may_read(ancestor)
        if readable[ancestor.id]:
            inherited[field] = {
                "value": entry["value"],
                "asset_id": ancestor.id,
                "asset_name": ancestor.name,
            }
        else:
            inherited[field] = {
                "value": None,
                "hidden": True,
                "asset_id": None,
                "asset_name": ANOTHER_ORGANISATION,
            }
    return inherited


def readable_site_asset(asset: GenericAsset) -> GenericAsset:
    """The highest ancestor of the asset (or the asset itself) that the viewer may read.

    Usually the site asset, unless the asset tree goes up into an organisation the viewer may not see.
    """
    site_asset = asset
    while site_asset.parent_asset is not None and viewer_may_read(
        site_asset.parent_asset
    ):
        site_asset = site_asset.parent_asset
    return site_asset


def editor_paths_and_url(
    asset: GenericAsset, config_name: str, paths: list[str]
) -> tuple[list[str], str]:
    """Order the paths of fields whose sensor was deleted, and link to the editor for them.

    Top-level fields come first, as these are what the flex-context editor can open directly,
    so the link opens it on the first of them.
    The flex-model editor is on the asset's Properties page, which the link goes to.

    :param config_name: "flex-context" or "flex-model".
    :returns: The ordered paths, and the editor's URL.
    """
    paths = sorted(paths, key=lambda path: (path.count(" > "), path))
    if config_name == "flex-model":
        return paths, url_for("AssetCrudUI:properties", id=asset.id)
    if " > " in paths[0]:
        return paths, url_for("AssetCrudUI:context", id=asset.id)
    return paths, url_for(
        "AssetCrudUI:context", id=asset.id, flex_context_field=paths[0]
    )


def deleted_sensor_references_toast(asset: GenericAsset) -> Markup | None:
    """The toast an asset's pages show while its flex-config has fields whose sensor was deleted.

    Deleting a sensor leaves the rest of each reference to it in place, such as its default and bounds,
    but the field needs a new sensor, and until it has one, saving its flex-config is refused.
    So each page of the asset points the user at the editor for it.

    Only a user who can edit the asset's flex-config is pointed at the editor, as no one else can save the fix.

    :returns: The toast's message, or None if no field lost its sensor, or the user cannot fix it.
    """
    if not user_can_access(asset, "edit-flex-config"):
        return None
    editors = (
        ("flex-context", asset.flex_context, "flex-context editor"),
        ("flex-model", asset.flex_model, "flex-model editor on the Properties page"),
    )
    parts = []
    for config_name, config, editor in editors:
        paths = unset_sensor_reference_paths(config)
        if not paths:
            continue
        paths, url = editor_paths_and_url(asset, config_name, paths)
        subject = (
            "A field in the {config} of this asset refers"
            if len(paths) == 1
            else "Fields in the {config} of this asset refer"
        )
        parts.append(
            Markup(
                subject
                + ' to a sensor that has been deleted: {fields}. <a href="{url}">Pick a new sensor in the {editor}</a>.'
            ).format(
                config=config_name, fields=", ".join(paths), url=url, editor=editor
            )
        )
    if not parts:
        return None
    return Markup(" ").join(
        parts
        + [
            Markup(
                "Until then, scheduling uses the default of such a field as a fixed value, or ignores the field."
            )
        ]
    )


def serialize_hidden_asset(node_id: str, parent_id: int | str | None = None) -> dict:
    """A node in the asset tree for assets the viewer may not read: no name, link, type or sensors."""
    serialized_asset = {
        "name": ANOTHER_ORGANISATION,
        "id": node_id,
        "asset_type": "",
        "link": None,
        "icon": svg_asset_icon_name(""),
        "tooltip": "An asset of another organisation",
        "sensors": [],
        "other_organisation": True,
    }
    if parent_id is not None:
        serialized_asset["parent"] = parent_id
    return serialized_asset


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
        if asset.parent_asset.account_id != asset.account_id:
            # Asset trees may span organisations: mark the child of another organisation than its parent's
            serialized_asset["other_organisation"] = True
            serialized_asset["tooltip"]["Organisation"] = (
                asset.owner.name if asset.owner is not None else "Public"
            )

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
    # A parent the viewer may not read (in another organisation) is shown without anything about it, nor what is above it.
    parent_is_hidden = asset.parent_asset is not None and not viewer_may_read(
        asset.parent_asset
    )
    if (
        asset.parent_asset
        and parent_depth < 2
        and not look_for_child
        and not parent_is_hidden
    ):
        parent_depth += 1
        assets += get_list_assets_chart(
            asset=asset.parent_asset,
            base_asset=base_asset,
            parent_depth=parent_depth,
            is_head=False if parent_depth < 2 else True,
        )
    else:
        if parent_is_hidden and parent_depth < 2 and not look_for_child:
            hidden_parent = serialize_hidden_asset(f"hidden-parent-of-{asset.id}")
            asset_def["parent"] = hidden_parent["id"]
            assets.append(hidden_parent)
        look_for_child = True
        parent_depth = (
            2  # Auto increase depth in the parents hierarchy is less than two
        )

    assets.append(asset_def)

    if look_for_child and child_depth < 2:
        child_depth += 1
        hidden_children = False
        for child in base_asset.child_assets:
            if not viewer_may_read(child):
                hidden_children = True
                continue
            assets += get_list_assets_chart(
                child,
                parent_depth=parent_depth,
                child_depth=child_depth,
                base_asset=child,
            )
        if hidden_children:
            # One node for the children in organisations the viewer may not read
            assets.append(
                serialize_hidden_asset(
                    f"hidden-children-of-{base_asset.id}", parent_id=base_asset.id
                )
            )

    return assets


def add_child_asset(asset: Asset, assets: list) -> list:
    """
    Add a child asset to the current assets list.
    This function is used to add a child asset to the current asset in the list of assets.
    :param asset:   The current asset to be used as parent.
    :param assets:  The list of assets.
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
