from flask import current_app
from sqlalchemy import delete

from flexmeasures.data import db
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.audit_log import AssetAuditLog
from flexmeasures.data.schemas.scheduling import DBFlexContextSchema
from flexmeasures.data.schemas.scheduling.storage import DBStorageFlexModelSchema
from dictdiffer import diff

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


def format_json_field_change(field_name: str, old_value, new_value) -> str:
    """
    Format JSON field changes using dictdiffer.

    This function attempts to provide a detailed diff of changes between two JSON-like structures.
    If the structures are not dicts or lists, or if an error occurs, it fall back to a simple change description.

    :param field_name: Name of the field being changed.
    :param old_value: The old value of the field.
    :param new_value: The new value of the field.
    :return: A formatted string describing the changes.

    **Example input 1**

    .. sourcecode:: json

        {
            "field_name": "flex_context",
            "old_value": {'site-production-capacity': '1500 kW', 'site-peak-production': '20000kW', 'inflexible-device-sensors': []},
            "new_value": {'site-production-capacity': '15000 kW', 'site-peak-production': '20000kW', 'inflexible-device-sensors': []}
        }

    **Example output 1**

    .. sourcecode:: text

        Updated: flex_context, change site-production-capacity:: 1500 kW -> 15000 kW

    **Example input 2**

    .. sourcecode:: json

        {
            "field_name": "flex_context",
            "old_value": {'site-production-capacity': '15000 kW', 'site-peak-production': '20000kW'},
            "new_value": {'site-peak-production': '20000kW'}
        }

    **Example output 2**

    .. sourcecode:: text
        Updated: flex_context, remove site-production-capacity
    """
    try:
        if isinstance(old_value, list):
            old_dict = {i: item for i, item in enumerate(old_value)}
            new_dict = {i: item for i, item in enumerate(new_value)}
        else:
            old_dict, new_dict = old_value, new_value

        if isinstance(old_dict, dict) and isinstance(new_dict, dict):
            diff_results = list(diff(old_dict, new_dict))
            changes = []
            for change_type, key, value in diff_results:
                if change_type == "change":
                    changes.append(f"change {key}: {value[0]} -> {value[1]}")
                elif change_type == "add":
                    for item in value:
                        changes.append(f"add {item[0]}: {item[1]}")
                elif change_type == "remove":
                    for item in value:
                        changes.append(f"remove {item[0]}")

            if changes:
                if len(changes) > 1:
                    changes_str = "\n".join(
                        f"{i}. {change}" for i, change in enumerate(changes, 1)
                    )
                else:
                    changes_str = changes[0]
                return f"Updated: {field_name}, {changes_str}"

        return f"Updated: {field_name}, From: {old_value}, To: {new_value}"
    except Exception as e:
        current_app.logger.error(
            f"Error formatting JSON field change for {field_name}: {e}"
        )
        return f"Updated: {field_name}, From: {old_value}, To: {new_value}"


def patch_asset(db_asset: GenericAsset, asset_data: dict) -> GenericAsset:
    """
    Patch an asset.

    Throws validation error as it checks JSON fields (e.g. attributes) for validity explicitly.
    Does not commit the session.
    Creates an audit log.
    """
    audit_log_data = list()

    # first special content
    schema_map = dict(
        flex_context=DBFlexContextSchema,
        flex_model=DBStorageFlexModelSchema,
    )
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
        if k in schema_map:
            # Validate the given schema
            schema_map[k]().load(v)

        if k.lower() in {"sensors_to_show", "flex_context", "flex_model"}:
            audit_log_data.append(format_json_field_change(k, getattr(db_asset, k), v))
        else:
            audit_log_data.append(
                f"Updated: {k}, From: {getattr(db_asset, k)}, To: {v}"
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
