from flask import current_app
from sqlalchemy import delete

from flexmeasures.data import db
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.audit_log import AssetAuditLog
from flexmeasures.data.schemas.scheduling import DBFlexContextSchema
from flexmeasures.data.schemas.scheduling.storage import DBStorageFlexModelSchema
from flexmeasures.data.schemas.generic_assets import SensorsToShowSchema

"""Services for managing assets"""


def create_asset(asset_data: dict) -> GenericAsset:
    """
    Create an asset.

    Does not validate data or commit the session.
    Creates an audit log.
    """
    if "external_id" in asset_data and str(asset_data["external_id"]).strip() == "":
        asset_data.pop("external_id")  # nothing to set, leave it as None
    asset = GenericAsset(**asset_data)
    db.session.add(asset)
    # assign asset id
    db.session.flush()

    AssetAuditLog.add_record(asset, f"Created asset '{asset.name}': {asset.id}")

    return asset


def _graph_label(graph) -> str:
    """Generate a label for a graph showing title and sensors."""
    title = graph.get("title") or "Untitled graph"
    plots = graph.get("plots", [])
    sensor_ids = []
    for p in plots:
        if "sensor" in p:
            sensor_ids.append(str(p["sensor"]))
        elif "sensors" in p:
            sensor_ids.extend(str(s) for s in p["sensors"])
    sensors_str = f"sensors [{', '.join(sensor_ids)}]" if sensor_ids else "no sensors"
    return f'"{title}" ({sensors_str})'


def _sensor_ids_in_graph(graph) -> list:
    """Extract all sensor IDs from a graph."""
    ids = []
    for p in graph.get("plots", []):
        if "sensor" in p:
            ids.append(p["sensor"])
        elif "sensors" in p:
            ids.extend(p["sensors"])
    return ids


def _describe_plot_changes(old_plots: list, new_plots: list) -> list:
    """Describe changes between old and new plots.

    Compares all keys generically rather than a fixed set, so future
    additions to the plot schema are diffed automatically.
    """
    import json as _json

    changes = []
    max_len = max(len(old_plots), len(new_plots))
    for pi in range(max_len):
        if pi >= len(old_plots):
            changes.append(f"added plot {pi + 1}: {_json.dumps(new_plots[pi])}")
        elif pi >= len(new_plots):
            changes.append(f"removed plot {pi + 1}")
        else:
            old_plot, new_plot = old_plots[pi], new_plots[pi]
            all_keys = sorted(set(old_plot) | set(new_plot))
            for key in all_keys:  # for instance, flex-context and flex-model
                ov = old_plot.get(key)
                nv = new_plot.get(key)
                if ov == nv:
                    continue
                if ov is None:
                    changes.append(f'plot {pi + 1}: set {key} to "{nv}"')
                elif nv is None:
                    changes.append(f"plot {pi + 1}: removed {key}")
                else:
                    changes.append(f'plot {pi + 1}: {key} "{ov}" → "{nv}"')
    return changes


def _describe_graph_changes(old_graph, new_graph, index: int) -> str | None:
    """Describe changes in a single graph. Returns None if no changes."""
    old_title = old_graph.get("title") or "Untitled"
    new_title = new_graph.get("title") or "Untitled"

    sub = []
    if old_title != new_title:
        sub.append(f'title: "{old_title}" → "{new_title}"')

    old_ids = _sensor_ids_in_graph(old_graph)
    new_ids = _sensor_ids_in_graph(new_graph)
    added_ids = [s for s in new_ids if s not in old_ids]
    removed_ids = [s for s in old_ids if s not in new_ids]
    if added_ids:
        sub.append(f"added sensors {added_ids}")
    if removed_ids:
        sub.append(f"removed sensors {removed_ids}")

    old_plots = old_graph.get("plots", [])
    new_plots = new_graph.get("plots", [])
    sub.extend(_describe_plot_changes(old_plots, new_plots))

    if sub:
        return f"Changed graph {index + 1} ({old_title}): {'; '.join(sub)}"
    return None


def _describe_sensors_to_show_changes(old_value, new_value) -> str:
    """Produce a readable summary of changes to sensors_to_show.

    Compares graphs by index and reports added/removed/changed graphs and sensors
    in plain language rather than raw path tuples.
    """
    old_list = old_value if isinstance(old_value, list) else []
    new_list = new_value if isinstance(new_value, list) else []

    changes = []
    max_len = max(len(old_list), len(new_list))
    for i in range(max_len):
        if i >= len(old_list):
            changes.append(f"Added graph {i + 1}: {_graph_label(new_list[i])}")
        elif i >= len(new_list):
            changes.append(f"Removed graph {i + 1}: {_graph_label(old_list[i])}")
        else:
            change = _describe_graph_changes(old_list[i], new_list[i], i)
            if change:
                changes.append(change)

    return (
        "\n".join(f"{i + 1}. {c}" for i, c in enumerate(changes))
        if changes
        else "No changes"
    )


_MISSING = object()


def _format_json_path(path: str, key) -> str:
    """Append a dict key or list index to a JSON-style path string."""
    if isinstance(key, int):
        return f"{path}[{key}]" if path else f"[{key}]"
    return f"{path}.{key}" if path else str(key)


def _collect_nested_changes(old_value, new_value, path: str = "") -> list[str]:
    """Collect readable change messages for nested dict/list structures."""
    if isinstance(old_value, dict) and isinstance(new_value, dict):
        changes = []
        for key in sorted(set(old_value) | set(new_value)):
            ov = old_value.get(key, _MISSING)
            nv = new_value.get(key, _MISSING)
            key_path = _format_json_path(path, key)
            if ov is _MISSING:
                changes.append(f"Added {key_path}: {nv}")
            elif nv is _MISSING:
                changes.append(f"Removed {key_path} (was: {ov})")
            else:
                changes.extend(_collect_nested_changes(ov, nv, key_path))
        return changes

    if isinstance(old_value, list) and isinstance(new_value, list):
        changes = []
        max_len = max(len(old_value), len(new_value))
        for index in range(max_len):
            item_path = _format_json_path(path, index)
            if index >= len(old_value):
                changes.append(f"Added {item_path}: {new_value[index]}")
            elif index >= len(new_value):
                changes.append(f"Removed {item_path} (was: {old_value[index]})")
            else:
                changes.extend(
                    _collect_nested_changes(
                        old_value[index], new_value[index], item_path
                    )
                )
        return changes

    if old_value != new_value:
        return [f"Changed {path}: {old_value} → {new_value}"]

    return []


def _describe_dict_changes(old_value: dict, new_value: dict) -> str:
    """Produce a readable summary of changes between nested dict/list structures."""
    changes = _collect_nested_changes(old_value, new_value)
    return (
        "\n".join(f"{i + 1}. {c}" for i, c in enumerate(changes))
        if changes
        else "No changes"
    )


def format_json_field_change(field_name: str, old_value, new_value) -> str:
    """Format JSON field changes into a human-readable audit log entry.

    Produces plain-language descriptions for sensors_to_show, flex_context, and
    flex_model changes. For generic JSON fields, nested dict/list structures are
    described recursively. Falls back to a simple before/after note for other
    fields or when an error occurs.

    :param field_name:  Name of the field being changed.
    :param old_value:   The old value of the field.
    :param new_value:   The new value of the field.
    :return:            A formatted string describing the changes.

    Examples
    ========

    >>> json = {
    ...     "field_name": "flex_model",
    ...     "old_value": {"production-capacity": "15 kW"},
    ...     "new_value": {"production-capacity": "15 kW", "storage-efficiency": "99.92%"}
    ... }
    >>> format_json_field_change(**json)
    'Updated flex_model:\\n1. Added storage-efficiency: 99.92%'

    >>> json = {
    ...     "field_name": "flex_context",
    ...     "old_value": {"site-production-capacity": "1500 kW", "site-peak-production": "20000kW"},
    ...     "new_value": {"site-production-capacity": "15000 kW", "site-peak-production": "20000kW"}
    ... }
    >>> format_json_field_change(**json)
    'Updated flex_context:\\n1. Changed site-production-capacity: 1500 kW → 15000 kW'

    >>> json = {
    ...     "field_name": "flex_context",
    ...     "old_value": {"site-production-capacity": "15000 kW", "site-peak-production": "20000kW"},
    ...     "new_value": {"site-peak-production": "20000kW"}
    ... }
    >>> format_json_field_change(**json)
    'Updated flex_context:\\n1. Removed site-production-capacity (was: 15000 kW)'

    >>> json = {
    ...     "field_name": "flex_model",
    ...     "old_value": {"soc-usage": ["3500 kW", {"sensor": 7}]},
    ...     "new_value": {"soc-usage": ["3500 kW", {"sensor": 8}]}
    ... }
    >>> format_json_field_change(**json)
    'Updated flex_model:\\n1. Changed soc-usage[1].sensor: 7 → 8'

    >>> json = {
    ...     "field_name": "sensors_to_show",
    ...     "old_value": [{"title": "Power", "plots": [{"sensor": 1}]}],
    ...     "new_value": [
    ...         {"title": "Power", "plots": [{"sensor": 1}, {"sensor": 2}]},
    ...         {"title": "Price", "plots": [{"sensor": 3}]},
    ...     ],
    ... }
    >>> format_json_field_change(**json)
    'Updated sensors_to_show:\\n1. Changed graph 1 (Power): added sensors [2]; added plot 2: {"sensor": 2}\\n2. Added graph 2: "Price" (sensors [3])'
    """
    try:
        if field_name == "sensors_to_show":
            detail = _describe_sensors_to_show_changes(old_value, new_value)
        elif isinstance(old_value, dict) and isinstance(new_value, dict):
            detail = _describe_dict_changes(old_value, new_value)
        else:
            return f"Updated {field_name}: {old_value} → {new_value}"

        return f"Updated {field_name}:\n{detail}"
    except Exception as e:
        current_app.logger.error(
            f"Error formatting JSON field change for {field_name}: {e}"
        )
        return f"Updated {field_name}: {old_value} → {new_value}"


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
        sensors_to_show=SensorsToShowSchema,
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
            # Validate the JSON field against the given schema
            if k != "sensors_to_show":
                schema_map[k]().load(v)
            else:
                # we use `deserialize here because the `SensorsToShowSchema` is a "fields.Field" object rather than a "Schema" object
                schema_map[k]().deserialize(v)

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
        if k == "external_id" and str(v).strip() == "":
            if db_asset.external_id is None:
                continue  # no change
            v = None  # set to None to remove external_id
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
