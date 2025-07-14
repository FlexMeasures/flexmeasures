from __future__ import annotations

from sqlalchemy import select
from flexmeasures import Sensor, Asset, Account
from flexmeasures.utils.flexmeasures_inflection import human_sorted
from flask import url_for, current_app


def get_breadcrumb_info(
    entity: Sensor | Asset | Account | None, current_page: str = None
) -> dict:
    breadcrumb = {
        "ancestors": get_ancestry(entity),
        "siblings": get_siblings(entity),
    }

    if entity is not None and isinstance(entity, Asset):
        # Add additional Views CTAs for Assets
        try:
            breadcrumb["current_asset_view"] = current_page
            breadcrumb["views"] = [
                {
                    "url": url_for("AssetCrudUI:context", id=entity.id),
                    "name": "Context",
                    "type": "Asset",
                },
                {
                    "url": url_for("AssetCrudUI:graphs", id=entity.id),
                    "name": "Graphs",
                    "type": "Asset",
                },
                {
                    "url": url_for("AssetCrudUI:properties", id=entity.id),
                    "name": "Properties",
                    "type": "Asset",
                },
                {
                    "url": url_for("AssetCrudUI:auditlog", id=entity.id),
                    "name": "Audit Log",
                    "type": "Asset",
                },
                {
                    "url": url_for("AssetCrudUI:status", id=entity.id),
                    "name": "Status",
                    "type": "Asset",
                },
            ]

        except Exception as e:
            print("Error in updating breadcrumb variables:", e)

    return breadcrumb


def get_ancestry(entity: Sensor | Asset | Account | None) -> list[dict]:
    """
    Return a list of ancestors meta data, with URLs for their pages, their name and type.
    This function calls itself recursively to go up the ancestral tree, up to the account.
    This function also allows customization for assets and sensors (for this, set "breadcrumb_ancestry" attribute).
    """
    custom_ancestry = None
    if entity is not None and not isinstance(entity, Account):
        custom_ancestry = entity.get_attribute("breadcrumb_ancestry")
    if custom_ancestry is not None and isinstance(custom_ancestry, list):
        # Append current Asset to the custom ancestry breadcrumb
        if entity is not None and isinstance(entity, Asset):
            current_entity_info = {
                "url": url_for("AssetCrudUI:get", id=entity.id),
                "name": entity.name,
                "type": "Asset",
            }
            custom_ancestry.append(current_entity_info)
        return custom_ancestry

    # Public account
    if entity is None:
        return [{"url": None, "name": "PUBLIC", "type": "Account"}]

    # account
    if isinstance(entity, Account):
        return [
            {
                "url": url_for("AccountCrudUI:get", account_id=entity.id),
                "name": entity.name,
                "type": "Account",
            }
        ]

    # sensor
    if isinstance(entity, Sensor):
        current_entity_info = [
            {
                "url": url_for("SensorUI:get", id=entity.id),
                "name": entity.name,
                "type": "Sensor",
            }
        ]

        return get_ancestry(entity.generic_asset) + current_entity_info

    # asset
    if isinstance(entity, Asset):
        current_entity_info = [
            {
                "url": url_for("AssetCrudUI:get", id=entity.id),
                "name": entity.name,
                "type": "Asset",
            }
        ]

        # asset without parent
        if entity.parent_asset is None:
            return get_ancestry(entity.owner) + current_entity_info
        else:  # asset with parent
            return get_ancestry(entity.parent_asset) + current_entity_info

    return []


def get_siblings(entity: Sensor | Asset | Account | None) -> list[dict]:
    """
    Return a list of siblings meta data, with URLs for their pages, name and type.
    This function also allows customization (for this, set "breadcrumb_siblings" attribute).
    """
    custom_siblings = None
    if entity is not None and not isinstance(entity, Account):
        custom_siblings = entity.get_attribute("breadcrumb_siblings")
    if custom_siblings is not None and isinstance(custom_siblings, list):
        return custom_siblings
    siblings = []
    if isinstance(entity, Sensor):
        siblings = [
            {
                "url": url_for("SensorUI:get", id=sensor.id),
                "name": sensor.name,
                "type": "Sensor",
            }
            for sensor in entity.generic_asset.sensors
        ]
    if isinstance(entity, Asset):
        if entity.parent_asset is not None:
            sibling_assets = entity.parent_asset.child_assets
        elif entity.owner is not None:
            session = current_app.db.session
            sibling_assets = session.scalars(
                select(Asset).filter(
                    Asset.parent_asset_id.is_(None), Asset.owner == entity.owner
                )
            ).all()
        else:
            session = current_app.db.session
            sibling_assets = session.scalars(
                select(Asset).filter(
                    Asset.account_id.is_(None), Asset.parent_asset_id.is_(None)
                )
            ).all()

        siblings = [
            {
                "url": url_for("AssetCrudUI:get", id=asset.id),
                "name": asset.name,
                "type": "Asset",
            }
            for asset in sibling_assets
        ]
    siblings = human_sorted(siblings, attr="name")
    return siblings
