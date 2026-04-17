import re
from copy import deepcopy
from typing import Any

from flask import current_app
from sqlalchemy import delete, select

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


def _graph_label(graph: dict[str, Any]) -> str:
    """Generate a compact label for one modern ``sensors_to_show`` graph entry.

    Expected input structure (a single graph entry):
    {
        "title": "Some graph title",  # optional
        "plots": [
            {"sensor": 1},
            {"sensors": [2, 3]},
            {"asset": 4239, "flex-model": "soc-min"},
        ]
    }

    We read ``title`` and scan ``plots`` for:
    - ``sensor`` / ``sensors`` keys
    - ``asset`` + ``flex-context``/``flex-model`` references

    to build a human-readable label used in audit log messages.

    Response example:
    >>> _graph_label({"title": "Power", "plots": [{"sensor": 1}, {"sensors": [2, 3]}]})
    '"Power" (sensors [1, 2, 3])'
    """
    title = graph.get("title") or "Untitled graph"
    plots = graph.get("plots", [])
    sensor_ids = []
    flex_refs = []
    for p in plots:
        if "sensor" in p:
            sensor_ids.append(str(p["sensor"]))
        elif "sensors" in p:
            sensor_ids.extend(str(s) for s in p["sensors"])
        elif "asset" in p and ("flex-context" in p or "flex-model" in p):
            if "flex-context" in p:
                flex_refs.append(
                    f"asset {p['asset']}, flex-context: {p['flex-context']}"
                )
            if "flex-model" in p:
                flex_refs.append(f"asset {p['asset']}, flex-model: {p['flex-model']}")

    summary_parts = []
    if sensor_ids:
        summary_parts.append(f"sensors [{', '.join(sensor_ids)}]")
    if flex_refs:
        summary_parts.append(f"refs [{'; '.join(flex_refs)}]")
    if not summary_parts:
        summary_parts.append("no sensors")

    return f'"{title}" ({", ".join(summary_parts)})'


def _describe_plot_key_changes(
    old_plot: dict, new_plot: dict, plot_number: int
) -> list:
    """Describe field-level changes between two plots."""
    changes = []
    all_keys = sorted(set(old_plot) | set(new_plot))
    for key in all_keys:  # for instance, flex-context and flex-model
        ov = old_plot.get(key)
        nv = new_plot.get(key)
        if ov == nv:
            continue
        if ov is None:
            changes.append(f'plot {plot_number}: set {key} to "{nv}"')
        elif nv is None:
            changes.append(f"plot {plot_number}: removed {key}")
        else:
            changes.append(f'plot {plot_number}: {key} "{ov}" → "{nv}"')
    return changes


def _describe_plot_replace_block(
    old_plots: list, new_plots: list, i1: int, i2: int, j1: int, j2: int
) -> list:
    """Describe a replacement block produced by SequenceMatcher opcodes."""
    import json as _json

    changes = []
    shared = min(i2 - i1, j2 - j1)
    for offset in range(shared):
        pi = i1 + offset
        pj = j1 + offset
        changes.extend(_describe_plot_key_changes(old_plots[pi], new_plots[pj], pj + 1))

    for pi in range(i1 + shared, i2):
        changes.append(f"removed plot {pi + 1}: {_json.dumps(old_plots[pi])}")
    for pj in range(j1 + shared, j2):
        changes.append(f"added plot {pj + 1}: {_json.dumps(new_plots[pj])}")
    return changes


def _describe_plot_changes(old_plots: list, new_plots: list) -> list:
    """Describe changes between old and new plots.

    Compares all keys generically rather than a fixed set, so future
    additions to the plot schema are diffed automatically.
    """
    import difflib as _difflib
    import json as _json

    changes = []
    old_serialized = [_json.dumps(p, sort_keys=True) for p in old_plots]
    new_serialized = [_json.dumps(p, sort_keys=True) for p in new_plots]

    matcher = _difflib.SequenceMatcher(
        a=old_serialized, b=new_serialized, autojunk=False
    )

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue

        if tag == "delete":
            for pi in range(i1, i2):
                changes.append(f"removed plot {pi + 1}: {_json.dumps(old_plots[pi])}")
            continue

        if tag == "insert":
            for pj in range(j1, j2):
                changes.append(f"added plot {pj + 1}: {_json.dumps(new_plots[pj])}")
            continue

        changes.extend(
            _describe_plot_replace_block(old_plots, new_plots, i1, i2, j1, j2)
        )

    return changes


def _describe_graph_changes(old_graph, new_graph, index: int) -> str | None:
    """Describe changes in a single graph. Returns None if no changes."""
    old_title = old_graph.get("title") or "Untitled"
    new_title = new_graph.get("title") or "Untitled"

    sub = []
    if old_title != new_title:
        sub.append(f'title: "{old_title}" → "{new_title}"')

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
    'Updated sensors_to_show:\\n1. Changed graph 1 (Power): added plot 2: {"sensor": 2}\\n2. Added graph 2: "Price" (sensors [3])'
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


def _copy_direct_sensors(
    source_asset: GenericAsset, copied_asset: GenericAsset
) -> dict[int, int]:
    """Copy sensors directly attached to one asset.

    Returns a mapping of original sensor ID -> new sensor ID.
    """
    from flexmeasures.data.models.time_series import Sensor
    from timely_beliefs.sensors.func_store import knowledge_horizons

    sensor_id_map: dict[int, int] = {}
    source_sensors = db.session.scalars(
        select(Sensor).filter(Sensor.generic_asset_id == source_asset.id)
    ).all()
    for source_sensor in source_sensors:
        sensor_kwargs: dict = {}
        for column in source_sensor.__table__.columns:
            if column.name in (
                "id",
                "generic_asset_id",
                "knowledge_horizon_fnc",
                "knowledge_horizon_par",
            ):
                continue
            sensor_kwargs[column.name] = deepcopy(getattr(source_sensor, column.name))
        sensor_kwargs["generic_asset_id"] = copied_asset.id
        knowledge_horizon_fnc = getattr(
            knowledge_horizons, source_sensor.knowledge_horizon_fnc
        )
        sensor_kwargs["knowledge_horizon"] = (
            knowledge_horizon_fnc,
            deepcopy(source_sensor.knowledge_horizon_par),
        )
        new_sensor = Sensor(**sensor_kwargs)
        db.session.add(new_sensor)
        db.session.flush()
        sensor_id_map[source_sensor.id] = new_sensor.id
    return sensor_id_map


_REMOVED = object()


def _is_sensor_on_public_asset(sensor_id: int) -> bool:
    """Return True if sensor_id belongs to a public asset (account_id is None)."""
    from flexmeasures.data.models.time_series import Sensor

    sensor = db.session.get(Sensor, sensor_id)
    if sensor is None:
        return False
    asset = db.session.get(GenericAsset, sensor.generic_asset_id)
    return asset is not None and asset.account_id is None


def _resolve_sensor_id(sensor_id: int, sensor_id_map: dict[int, int]) -> "int | object":
    if sensor_id in sensor_id_map:
        return sensor_id_map[sensor_id]
    if _is_sensor_on_public_asset(sensor_id):
        return sensor_id
    return _REMOVED


def _replace_sensor_refs(data, sensor_id_map: dict[int, int]):
    """Recursively replace sensor IDs inside a nested JSON structure."""
    if isinstance(data, dict):
        result: dict = {}
        for key, value in data.items():
            if key == "sensor" and isinstance(value, int):
                resolved = _resolve_sensor_id(value, sensor_id_map)
                if resolved is _REMOVED:
                    return _REMOVED
                result[key] = resolved
            elif key == "sensors" and isinstance(value, list):
                new_list = []
                for v in value:
                    if not isinstance(v, int):
                        new_list.append(v)
                        continue
                    resolved = _resolve_sensor_id(v, sensor_id_map)
                    if resolved is not _REMOVED:
                        new_list.append(resolved)
                result[key] = new_list
            else:
                processed = _replace_sensor_refs(value, sensor_id_map)
                if processed is not _REMOVED:
                    result[key] = processed
        return result
    if isinstance(data, list):
        return [
            (
                _resolve_sensor_id(item, sensor_id_map)
                if isinstance(item, int)
                else _replace_sensor_refs(item, sensor_id_map)
            )
            for item in data
        ]
    return data


def _update_sensor_refs_in_subtree(
    asset: GenericAsset, sensor_id_map: dict[int, int]
) -> None:
    """Update sensor refs in flex_context, flex_model, sensors_to_show fields."""
    if asset.flex_context:
        result = _replace_sensor_refs(deepcopy(asset.flex_context), sensor_id_map)
        asset.flex_context = result if result is not _REMOVED else {}
    if asset.flex_model:
        result = _replace_sensor_refs(deepcopy(asset.flex_model), sensor_id_map)
        asset.flex_model = result if result is not _REMOVED else {}
    if asset.sensors_to_show:
        result = _replace_sensor_refs(deepcopy(asset.sensors_to_show), sensor_id_map)
        asset.sensors_to_show = result if result is not _REMOVED else []
    if asset.sensors_to_show_as_kpis:
        result = _replace_sensor_refs(
            deepcopy(asset.sensors_to_show_as_kpis), sensor_id_map
        )
        asset.sensors_to_show_as_kpis = result if result is not _REMOVED else []
    children = db.session.scalars(
        select(GenericAsset).filter(GenericAsset.parent_asset_id == asset.id)
    ).all()
    for child in children:
        _update_sensor_refs_in_subtree(child, sensor_id_map)


def _copy_asset_subtree(
    source_asset: GenericAsset,
    destination_account_id: int | None,
    destination_parent_asset_id: int | None,
    add_copy_suffix: bool,
) -> tuple[GenericAsset, dict[int, int]]:
    """Recursively copy one asset and all descendants. Returns (copied_root, sensor_id_map)."""
    asset_kwargs: dict = {}
    for column in source_asset.__table__.columns:
        if column.name in ("id", "parent_asset_id", "account_id"):
            continue
        asset_kwargs[column.name] = deepcopy(getattr(source_asset, column.name))
    asset_kwargs["account_id"] = destination_account_id
    asset_kwargs["parent_asset_id"] = destination_parent_asset_id

    if add_copy_suffix:
        asset_kwargs["name"] = _determine_copy_name(
            source_asset.name, destination_parent_asset_id, destination_account_id
        )

    copied_asset = GenericAsset(**asset_kwargs)
    db.session.add(copied_asset)
    db.session.flush()

    sensor_id_map = _copy_direct_sensors(source_asset, copied_asset)

    children = db.session.scalars(
        select(GenericAsset).filter(GenericAsset.parent_asset_id == source_asset.id)
    ).all()
    for child in children:
        _, child_sensor_map = _copy_asset_subtree(
            child,
            destination_account_id=destination_account_id,
            destination_parent_asset_id=copied_asset.id,
            add_copy_suffix=False,
        )
        sensor_id_map.update(child_sensor_map)

    return copied_asset, sensor_id_map


def _determine_copy_name(
    source_name: str,
    parent_asset_id: int | None,
    account_id: int | None,
) -> str:
    """Return the next available copy name."""
    query = select(GenericAsset.name).filter(
        GenericAsset.account_id == account_id,
        GenericAsset.parent_asset_id == parent_asset_id,
    )
    existing_names = set(db.session.scalars(query).all())

    first_copy_name = f"{source_name} (Copy)"
    if first_copy_name not in existing_names:
        return first_copy_name

    copy_name_pattern = re.compile(
        r"^" + re.escape(source_name) + r" \(Copy(?: (\d+))?\)$"
    )
    max_index = 1
    for existing_name in existing_names:
        match = copy_name_pattern.match(existing_name)
        if match:
            index = match.group(1)
            copy_index = int(index) if index is not None else 1
            if copy_index > max_index:
                max_index = copy_index
    return f"{source_name} (Copy {max_index + 1})"


def copy_asset(
    source_asset: GenericAsset,
    destination_account_id: int | None = None,
    destination_parent_asset_id: int | None = None,
) -> GenericAsset:
    """Copy an asset and all its descendants (sensors, children, flex config).

    The copied root asset gets a name with a "(Copy)" suffix.
    Sensor references in flex_context, flex_model, sensors_to_show are updated
    to point to the new sensor IDs.

    Does not commit the session.
    """
    if destination_account_id is None:
        destination_account_id = source_asset.account_id
    if destination_parent_asset_id is None:
        destination_parent_asset_id = source_asset.parent_asset_id

    # Guard: cannot copy to a descendant of itself
    if destination_parent_asset_id is not None:
        candidate = db.session.get(GenericAsset, destination_parent_asset_id)
        while candidate is not None:
            if candidate.id == source_asset.id:
                raise ValueError(
                    "Invalid copy target: cannot copy an asset to itself or any of its descendants."
                )
            candidate = (
                db.session.get(GenericAsset, candidate.parent_asset_id)
                if candidate.parent_asset_id
                else None
            )

    copied_root, sensor_id_map = _copy_asset_subtree(
        source_asset,
        destination_account_id=destination_account_id,
        destination_parent_asset_id=destination_parent_asset_id,
        add_copy_suffix=True,
    )

    _update_sensor_refs_in_subtree(copied_root, sensor_id_map)

    AssetAuditLog.add_record(
        copied_root,
        f"Copied asset '{source_asset.name}' (id={source_asset.id}) to '{copied_root.name}': {copied_root.id}",
    )

    return copied_root
