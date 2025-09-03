from flask import current_app
from sqlalchemy import delete

from flexmeasures.data import db
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.audit_log import AssetAuditLog
from flexmeasures.data.schemas.scheduling import DBFlexContextSchema

"""Services for managing assets"""


def create_asset(asset_data: dict) -> GenericAsset:
    """
    Create an asset.

    Does not validate data or commit the session.
    Creates an audit log.
    """
    asset = GenericAsset(**asset_data)
    db.session.add(asset)
    # assign asset id
    db.session.flush()

    AssetAuditLog.add_record(asset, f"Created asset '{asset.name}': {asset.id}")

    return asset


def patch_asset(db_asset: GenericAsset, asset_data: dict) -> GenericAsset:
    """
    Patch an asset.

    Throws validation error as it checks JSON fields (e.g. attributes) for validity explicitly.
    Does not commit the session.
    Creates an audit log.
    """
    audit_log_data = list()

    # first special content
    for k, v in asset_data.items():
        if getattr(db_asset, k) == v:
            continue
        if k == "attributes":
            current_attributes = getattr(db_asset, k)
            for attr_key, attr_value in v.items():
                if current_attributes.get(attr_key) != attr_value:
                    audit_log_data.append(
                        f"Updated Attr: {attr_key}, From: {current_attributes.get(attr_key)}, To: {attr_value}"
                    )
            continue
        if k == "flex_context":
            try:
                # Validate the flex context schema
                DBFlexContextSchema().load(v)
            except Exception as e:
                return {"error": str(e)}, 422

        audit_log_data.append(
            f"Updated Field: {k}, From: {getattr(db_asset, k)}, To: {v}"
        )

    # Iterate over each field or attribute updates and create a separate audit log entry for each.
    for event in audit_log_data:
        AssetAuditLog.add_record(db_asset, event)

    for k, v in asset_data.items():
        setattr(db_asset, k, v)

    return db_asset


def delete_asset(asset: GenericAsset):
    """
    Delete an asset.

    Does not commit the session.
    Creates an audit log.
    """
    asset_name, asset_id = asset.name, asset.id
    AssetAuditLog.add_record(asset, f"Deleted asset '{asset_name}': {asset_id}")

    db.session.execute(delete(GenericAsset).filter_by(id=asset.id))
    current_app.logger.info("Deleted asset '%s'." % asset_name)
