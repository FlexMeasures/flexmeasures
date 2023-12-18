from __future__ import annotations

from flexmeasures import Sensor, Asset, Account
from flask import url_for


def get_breadcrumb_info(entity: Sensor | Asset | Account | None) -> dict:
    return {
        "ancestors": get_ancestry(entity),
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
