from __future__ import annotations

from sqlalchemy import select
from flexmeasures import Sensor, Asset, Account
from flexmeasures.utils.flexmeasures_inflection import human_sorted
from flask import url_for, current_app


def get_breadcrumb_info(entity: Sensor | Asset | Account | None) -> dict:
    return {
        "ancestors": get_ancestry(entity),
        "siblings": get_siblings(entity),
    }


def get_ancestry(entity: Sensor | Asset | Account | None) -> list[dict]:
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
            sibling_assets = entity.owner.generic_assets
        else:
            session = current_app.db.session
            sibling_assets = session.scalars(
                select(Asset).filter(Asset.account_id.is_(None))
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
