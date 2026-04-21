from __future__ import annotations

import json
import time
import hashlib
from datetime import datetime, timedelta
from typing import Any
from flask import current_app
from sqlalchemy import delete

from isodate import duration_isoformat
from timely_beliefs import BeliefsDataFrame
import pandas as pd

from humanize.time import precisedelta
from humanize import naturaldelta

from flexmeasures.data.models.time_series import TimedBelief


import sqlalchemy as sa

from flexmeasures.data import db
from flexmeasures import Sensor, Account, Asset
from flexmeasures.data.models.audit_log import AssetAuditLog
from flexmeasures.data.models.data_sources import DataSource, DEFAULT_DATASOURCE_TYPES
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.schemas.reporting import StatusSchema
from flexmeasures.utils.time_utils import server_now


_REMOVE = object()


def _prune_flex_config_sensor_refs(
    value: dict[str, Any] | list[Any] | int | str | None, sensor_id: int
) -> tuple[dict[str, Any] | list[Any] | int | str | None | object, bool]:
    """Recursively remove sensor references from nested flex_model/flex_context JSON structures.

    This function handles deeply nested JSON objects and lists from flex_model and flex_context
    JSONB columns. It scans for sensor references in two forms:
    - Direct objects: {"sensor": sensor_id_to_remove}
    - Lists: [sensor_id_to_remove, ...] in "inflexible-device-sensors" keys

    Args:
        value: A JSON-like value (dict, list, int, str, None) from flex_model/flex_context.
               Can be arbitrarily nested.
        sensor_id: The ID of the sensor to remove references to.

    Returns:
        A tuple (pruned_value, changed):
        - pruned_value: The value with sensor references removed. Can be:
            - `_REMOVE` (sentinel object): Remove this entire entry from parent
            - A pruned dict/list/scalar: The value with refs removed
        - changed (bool): True if any references were actually removed.

    Example:
        >>> value = {"soc-max": {"sensor": 42}, "limit": "10 kW"}
        >>> pruned, did_change = _prune_flex_config_sensor_refs(value, sensor_id=42)
        >>> pruned
        {'limit': '10 kW'}
        >>> did_change
        True
    """
    if isinstance(value, dict):
        # Direct sensor reference object (for example {"sensor": 12})
        if set(value.keys()) == {"sensor"} and value.get("sensor") == sensor_id:
            return _REMOVE, True

        changed = False
        pruned_dict: dict[str, Any] = {}
        for k, v in value.items():
            if k == "inflexible-device-sensors" and isinstance(v, list):
                new_list = [entry for entry in v if entry != sensor_id]
                if len(new_list) != len(v):
                    changed = True
                pruned_dict[k] = new_list
                continue

            new_v, was_changed = _prune_flex_config_sensor_refs(v, sensor_id)
            changed = changed or was_changed
            if new_v is _REMOVE:
                changed = True
                continue
            pruned_dict[k] = new_v
        return pruned_dict, changed

    if isinstance(value, list):
        changed = False
        pruned_list: list[Any] = []
        for item in value:
            new_item, was_changed = _prune_flex_config_sensor_refs(item, sensor_id)
            changed = changed or was_changed
            if new_item is _REMOVE:
                changed = True
                continue
            pruned_list.append(new_item)
        return pruned_list, changed

    return value, False


def _prune_sensors_to_show_refs(
    value: list[Any] | None, sensor_id: int
) -> tuple[list[Any] | None, bool]:
    """Remove sensor references from sensors_to_show JSON list.

    This function handles sensors_to_show lists which support multiple entry formats:
    - Bare sensor IDs: [42, 43, ...]
    - Grouped sensor IDs: [42, [43, 44], ...] (nested lists)
    - Dict entries: [{"sensor": 42, ...}, ...] (delegated to _prune_sensors_to_show_entry)

    Args:
        value: The sensors_to_show JSON list (or None). Each entry can be an int, list of ints, or dict.
        sensor_id: The ID of the sensor to remove references to.

    Returns:
        A tuple (pruned_list, changed):
        - pruned_list: The list with sensor references removed (or empty lists filtered out).
                       Returns None/value unchanged if input is not a list.
        - changed (bool): True if any references were actually removed.

    Example:
        >>> value = [42, [43, 42], {"sensor": 42}]
        >>> pruned, did_change = _prune_sensors_to_show_refs(value, sensor_id=42)
        >>> pruned
        [[43]]
        >>> did_change
        True
    """
    if not isinstance(value, list):
        return value, False

    changed = False
    cleaned: list[Any] = []

    for entry in value:
        if isinstance(entry, int):
            if entry == sensor_id:
                changed = True
                continue
            cleaned.append(entry)
            continue

        if isinstance(entry, list):
            new_group = [sid for sid in entry if sid != sensor_id]
            if len(new_group) != len(entry):
                changed = True
            if new_group:
                cleaned.append(new_group)
            else:
                changed = True
            continue

        if isinstance(entry, dict):
            pruned_entry, entry_changed = _prune_sensors_to_show_entry(entry, sensor_id)
            changed = changed or entry_changed
            if pruned_entry is _REMOVE:
                continue
            cleaned.append(pruned_entry)
            continue

        cleaned.append(entry)

    return cleaned, changed


def _prune_sensors_to_show_entry(
    entry: dict[str, Any], sensor_id: int
) -> tuple[dict[str, Any] | object, bool]:
    """Remove sensor references from a single sensors_to_show dict entry.

    Handles three field types within a dict entry:
    - "sensor": Direct sensor ID reference → remove if matches
    - "sensors": List of sensor IDs → filter out matching IDs
    - "plots": List of plot dicts, each may contain "sensor" or "sensors" → recurse

    Args:
        entry: A dict from the sensors_to_show list (e.g., {"sensor": 42, "title": "..."}).
        sensor_id: The ID of the sensor to remove references to.

    Returns:
        A tuple (pruned_entry, changed):
        - pruned_entry: Can be:
            - `_REMOVE`: Remove this entire entry from parent list
            - Modified entry dict: The entry with refs removed
        - changed (bool): True if any references were removed.

    Example:
        >>> entry = {"sensor": 42, "title": "Power"}
        >>> pruned, did_change = _prune_sensors_to_show_entry(entry, sensor_id=42)
        >>> pruned is _REMOVE
        True
    """
    if "sensor" in entry:
        if entry.get("sensor") == sensor_id:
            return _REMOVE, True
        return entry, False

    if "sensors" in entry and isinstance(entry["sensors"], list):
        new_sensors = [sid for sid in entry["sensors"] if sid != sensor_id]
        changed = len(new_sensors) != len(entry["sensors"])
        if not new_sensors:
            return _REMOVE, True
        copied = dict(entry)
        copied["sensors"] = new_sensors
        return copied, changed

    if "plots" in entry and isinstance(entry["plots"], list):
        changed = False
        new_plots: list[Any] = []
        for plot in entry["plots"]:
            if not isinstance(plot, dict):
                new_plots.append(plot)
                continue
            if plot.get("sensor") == sensor_id:
                changed = True
                continue
            if "sensors" in plot and isinstance(plot["sensors"], list):
                new_sensors = [sid for sid in plot["sensors"] if sid != sensor_id]
                if len(new_sensors) != len(plot["sensors"]):
                    changed = True
                if not new_sensors:
                    changed = True
                    continue
                copied_plot = dict(plot)
                copied_plot["sensors"] = new_sensors
                new_plots.append(copied_plot)
            else:
                new_plots.append(plot)

        if not new_plots:
            return _REMOVE, True
        copied = dict(entry)
        copied["plots"] = new_plots
        return copied, changed

    return entry, False


def _prune_sensors_to_show_as_kpis_refs(
    value: list[Any] | None, sensor_id: int
) -> tuple[list[Any] | None, bool]:
    """Remove sensor references from sensors_to_show_as_kpis JSON list.

    This function handles sensors_to_show_as_kpis lists which support:
    - Bare sensor IDs: [42, 43, ...]
    - Dict entries: [{"sensor": 42, "title": "...", "function": "sum"}, ...]

    Args:
        value: The sensors_to_show_as_kpis JSON list (or None). Each entry is an int or dict.
        sensor_id: The ID of the sensor to remove references to.

    Returns:
        A tuple (pruned_list, changed):
        - pruned_list: The list with sensor references removed.
                       Returns None/value unchanged if input is not a list.
        - changed (bool): True if any references were actually removed.

    Example:
        >>> value = [42, {"sensor": 42, "title": "Temp KPI", "function": "sum"}]
        >>> pruned, did_change = _prune_sensors_to_show_as_kpis_refs(value, sensor_id=42)
        >>> pruned
        []
        >>> did_change
        True
    """
    if not isinstance(value, list):
        return value, False

    changed = False
    cleaned: list[Any] = []
    for entry in value:
        if isinstance(entry, int) and entry == sensor_id:
            changed = True
            continue
        if isinstance(entry, dict) and entry.get("sensor") == sensor_id:
            changed = True
            continue
        cleaned.append(entry)

    return cleaned, changed


def cleanup_sensor_references_in_assets(
    sensor_id: int, sensor_name: str | None = None
) -> int:
    """Remove references to a sensor in JSONB config fields across assets.

    Returns the number of updated assets.
    """

    vars_json = sa.func.jsonb_build_object("sid", sensor_id)
    candidates = db.session.scalars(
        sa.select(GenericAsset).where(
            sa.or_(
                sa.func.jsonb_path_exists(
                    GenericAsset.flex_model,
                    "$.**.sensor ? (@ == $sid)",
                    vars_json,
                ),
                sa.func.jsonb_path_exists(
                    GenericAsset.flex_context,
                    "$.**.sensor ? (@ == $sid)",
                    vars_json,
                ),
                sa.func.jsonb_path_exists(
                    GenericAsset.flex_context,
                    '$."inflexible-device-sensors"[*] ? (@ == $sid)',
                    vars_json,
                ),
                sa.func.jsonb_path_exists(
                    GenericAsset.sensors_to_show,
                    "$.**.sensor ? (@ == $sid)",
                    vars_json,
                ),
                sa.func.jsonb_path_exists(
                    GenericAsset.sensors_to_show,
                    "$.**.sensors[*] ? (@ == $sid)",
                    vars_json,
                ),
                sa.func.jsonb_path_exists(
                    GenericAsset.sensors_to_show,
                    "$[*] ? (@ == $sid)",
                    vars_json,
                ),
                sa.func.jsonb_path_exists(
                    GenericAsset.sensors_to_show_as_kpis,
                    "$.**.sensor ? (@ == $sid)",
                    vars_json,
                ),
            )
        )
    ).all()

    changed_assets = 0
    for asset in candidates:
        flex_model, flex_model_was_updated = _prune_flex_config_sensor_refs(
            asset.flex_model, sensor_id
        )
        flex_context, flex_context_was_updated = _prune_flex_config_sensor_refs(
            asset.flex_context, sensor_id
        )
        sensors_to_show, sensors_to_show_was_updated = _prune_sensors_to_show_refs(
            asset.sensors_to_show, sensor_id
        )
        sensors_to_show_as_kpis, sensors_to_show_as_kpis_was_updated = (
            _prune_sensors_to_show_as_kpis_refs(
                asset.sensors_to_show_as_kpis, sensor_id
            )
        )

        changed = any(
            (
                flex_model_was_updated,
                flex_context_was_updated,
                sensors_to_show_was_updated,
                sensors_to_show_as_kpis_was_updated,
            )
        )
        if not changed:
            continue

        changed_field_events = (
            (flex_model_was_updated, "flex-model"),
            (flex_context_was_updated, "flex-context"),
            (sensors_to_show_was_updated, "sensors-to-show"),
            (sensors_to_show_as_kpis_was_updated, "sensors-to-show-as-kpis"),
        )
        for field_changed, field_name in changed_field_events:
            if not field_changed:
                continue
            sensor_label = (
                f"'{sensor_name}': {sensor_id}" if sensor_name else str(sensor_id)
            )
            AssetAuditLog.add_record(
                asset,
                f"Removed sensor reference {sensor_label} from {field_name} (because sensor has been deleted).",
            )

        asset.flex_model = flex_model
        asset.flex_context = flex_context
        asset.sensors_to_show = sensors_to_show
        asset.sensors_to_show_as_kpis = sensors_to_show_as_kpis
        db.session.add(asset)
        changed_assets += 1

    return changed_assets


def get_sensors(
    account: Account | list[Account] | None,
    include_public_assets: bool = False,
    sensor_id_allowlist: list[int] | None = None,
    sensor_name_allowlist: list[str] | None = None,
) -> list[Sensor]:
    """Return a list of Sensor objects that belong to the given account, and/or public sensors.

    :param account:                 select only sensors from this account (or list of accounts)
    :param include_public_assets:   if True, include sensors that belong to a public asset
    :param sensor_id_allowlist:     optionally, allow only sensors whose id is in this list
    :param sensor_name_allowlist:   optionally, allow only sensors whose name is in this list
    """
    sensor_query = sa.select(Sensor)
    if isinstance(account, list):
        accounts = account
    else:
        accounts: list = [account] if account else []
    account_ids: list = [acc.id for acc in accounts]

    sensor_query = sensor_query.join(
        GenericAsset, GenericAsset.id == Sensor.generic_asset_id
    ).filter(Sensor.generic_asset_id == GenericAsset.id)
    if include_public_assets:
        sensor_query = sensor_query.filter(
            sa.or_(
                GenericAsset.account_id.in_(account_ids),
                GenericAsset.account_id.is_(None),
            )
        )
    else:
        sensor_query = sensor_query.filter(GenericAsset.account_id.in_(account_ids))
    if sensor_id_allowlist:
        sensor_query = sensor_query.filter(Sensor.id.in_(sensor_id_allowlist))
    if sensor_name_allowlist:
        sensor_query = sensor_query.filter(Sensor.name.in_(sensor_name_allowlist))

    return db.session.scalars(sensor_query).all()


def _get_sensor_bdfs_by_source_type(
    sensor: Sensor, staleness_search: dict
) -> dict[str, BeliefsDataFrame] | None:
    """Get latest event, split by source type for a given sensor with given search parameters.
    We only look for the default data source types!
    """
    bdfs_by_source = dict()
    for source_type in DEFAULT_DATASOURCE_TYPES:
        bdf = TimedBelief.search(
            sensors=sensor,
            most_recent_only=True,
            source_types=[source_type],
            **staleness_search,
        )
        if not bdf.empty:
            bdfs_by_source[source_type] = bdf
    return None if not bdfs_by_source else bdfs_by_source


def get_staleness_start_times(
    sensor: Sensor, staleness_search: dict, now: datetime
) -> dict[str, timedelta] | None:
    """Get staleness start times for a given sensor by source.
    Also add whether there has any relevant data (for forecasters and schedulers this is future data).
    For scheduler and forecaster sources staleness start is latest event start time.

    For other sources staleness start is the knowledge time of the sensor's most recent event.
    This knowledge time represents when you could have known about the event
    (specifically, when you could have formed an ex-post belief about it).
    """
    staleness_bdfs = _get_sensor_bdfs_by_source_type(
        sensor=sensor, staleness_search=staleness_search
    )
    if staleness_bdfs is None:
        return None

    start_times = dict()
    for source_type, bdf in staleness_bdfs.items():
        time_column = "knowledge_times"
        source_type = str(source_type)
        has_relevant_data = True
        if source_type in ("scheduler", "forecaster"):
            # filter to get only future events
            bdf_filtered = bdf[bdf.event_starts > now]
            time_column = "event_starts"
            if bdf_filtered.empty:
                has_relevant_data = False
                bdf_filtered = bdf
            bdf = bdf_filtered
        start_times[source_type] = (
            has_relevant_data,
            getattr(bdf, time_column)[-1] if not bdf.empty else None,
        )

    return start_times


def get_stalenesses(
    sensor: Sensor, staleness_search: dict, now: datetime
) -> dict[str, timedelta] | None:
    """Get the staleness of the sensor split by source.

    The staleness is defined relative to the knowledge time of the most recent event, rather than to its belief time.
    Basically, that means that we don't really care when the data arrived,
    as long as the available data is about what we should be able to know by now.

    :param sensor:              The sensor to compute the staleness for.
    :param staleness_search:    Deserialized keyword arguments to `TimedBelief.search`.
    :param now:                 Datetime representing now, used both to mask future beliefs,
                                and to measures staleness against.
    """

    # Mask beliefs before now
    staleness_search = staleness_search.copy()  # no inplace operations
    staleness_search["beliefs_before"] = min(
        now, staleness_search.get("beliefs_before", now)
    )

    staleness_start_times = get_staleness_start_times(
        sensor=sensor, staleness_search=staleness_search, now=now
    )
    if staleness_start_times is None:
        return None

    stalenesses = dict()
    for source_type, (has_relevant_data, start_time) in staleness_start_times.items():
        stalenesses[str(source_type)] = (
            has_relevant_data,
            None if start_time is None else now - start_time,
        )

    return stalenesses


def get_status_specs(sensor: Sensor) -> dict:
    """Get status specs from a given sensor."""

    # Check for explicitly defined status specs
    status_specs = sensor.attributes.get("status_specs", dict())
    if status_specs:
        return status_specs

    status_specs["staleness_search"] = {}
    # Consider forecast or schedule data stale if it is less than 12 hours in the future
    status_specs["max_future_staleness"] = "-PT12H"

    # Default to status specs for economical sensors with daily updates
    if sensor.knowledge_horizon_fnc == "x_days_ago_at_y_oclock":
        status_specs["max_staleness"] = "P1D"
        status_specs["staleness_search"] = {}
    else:
        # Default to status specs indicating staleness after knowledge time + 2 sensor resolutions
        status_specs["staleness_search"] = {}
        status_specs["max_staleness"] = duration_isoformat(sensor.event_resolution * 2)
    return status_specs


def get_statuses(
    sensor: Sensor,
    now: datetime,
    status_specs: dict | None = None,
) -> list[dict]:
    """Get the status of the sensor by source type.
    Main part of result here is a stale value, which is True if the sensor is stale, False otherwise.
    Other values are just context information for the stale value.
    """
    if status_specs is None:
        status_specs = get_status_specs(sensor=sensor)
    status_specs = StatusSchema().load(status_specs)
    max_staleness = status_specs.pop("max_staleness")
    max_future_staleness = status_specs.pop("max_future_staleness")
    staleness_search = status_specs.pop("staleness_search")
    stalenesses = get_stalenesses(
        sensor=sensor,
        staleness_search=staleness_search,
        now=now,
    )

    statuses = list()
    for source_type, (has_relevant_data, staleness) in (
        stalenesses or {None: (True, None)}
    ).items():
        if staleness is None or not has_relevant_data:
            staleness_since = now - staleness if not has_relevant_data else None
            stale = True
            reason = (
                "no data recorded"
                if staleness is None
                else "Found no future data which this source should have"
            )
            staleness = None
        else:
            max_source_staleness = (
                max_staleness if staleness > timedelta(0) else max_future_staleness
            )
            staleness_since = now - staleness
            stale = staleness > max_source_staleness
            timeline = "old" if staleness > timedelta(0) else "in the future"
            reason_part = ""
            if staleness > timedelta(0):
                reason_part = (
                    "which is not more" if not stale else "but should not be more"
                )
            else:
                reason_part = "which is not less" if not stale else "but should be more"
            staleness = staleness if staleness > timedelta(0) else -staleness
            reason = f"most recent data is {precisedelta(staleness)} {timeline}, {reason_part} than {precisedelta(max_source_staleness)} {timeline}"

        statuses.append(
            dict(
                staleness=staleness,
                stale=stale,
                staleness_since=staleness_since,
                reason=reason,
                source_type=source_type,
            )
        )

    return statuses


def _get_sensor_asset_relation(
    asset: Asset,
    sensor: Sensor,
    inflexible_device_sensors: list[Sensor],
    context_sensors: dict[str, Sensor],
) -> str:
    """Get the relation of a sensor to an asset."""
    relations = list()
    if sensor.generic_asset_id == asset.id:
        relations.append("sensor belongs to this asset")
    inflexible_device_sensors_ids = {sensor.id for sensor in inflexible_device_sensors}
    if sensor.id in inflexible_device_sensors_ids:
        relations.append("flex context (inflexible device)")
    for field, ctxt_sensor in context_sensors.items():
        if sensor.id == ctxt_sensor.id:
            relations.append(f"flex context ({field})")
    return ";".join(relations)


def get_asset_sensors_metadata(
    asset: Asset,
    now: datetime = None,
) -> list[dict]:
    """
    Get the metadata of sensors for a given asset and its children.

    :param asset: Asset to get the sensors for.
    :param now: Datetime representing now, used to get the status of the sensors.
    :return: A list of dictionaries, each representing a sensor's metadata.
    """

    if not now:
        now = server_now()

    sensors = []
    sensor_ids = set()
    inflexible_device_sensors = asset.get_inflexible_device_sensors()
    context_sensors = {
        field: Sensor.query.get(asset.flex_context[field]["sensor"])
        for field in asset.flex_context
        if isinstance(asset.flex_context[field], dict)
        and field != "inflexible-device-sensors"
    }

    # Get sensors to show using the validate_sensors_to_show method
    sensors_to_show = []
    validated_asset_sensors = asset.validate_sensors_to_show(
        suggest_default_sensors=False
    )
    sensor_groups = [
        sensor["sensors"] for sensor in validated_asset_sensors if sensor is not None
    ]
    merged_sensor_groups = sum(sensor_groups, [])
    sensors_to_show.extend(merged_sensor_groups)

    sensors_list = [
        *inflexible_device_sensors,
        *context_sensors.values(),
        *sensors_to_show,
    ]

    for sensor in sensors_list:
        if sensor is None or sensor.id in sensor_ids:
            continue
        sensor_status = {}
        sensor_status["id"] = sensor.id
        sensor_status["name"] = sensor.name
        sensor_status["asset_name"] = sensor.generic_asset.name
        sensor_ids.add(sensor.id)
        sensors.append(sensor_status)

    return sensors


def serialize_sensor_status_data(
    sensor: Sensor,
) -> list[dict]:
    """
    Serialize the status of a sensor belonging to an asset.

    :param sensor: Sensor to get the status of
    :return: A list of dictionaries, each representing the statuses of the sensor - one status per data source type that stored data on that sensor
    """
    asset = sensor.generic_asset
    sensor_statuses = get_statuses(sensor=sensor, now=server_now())
    inflexible_device_sensors = asset.get_inflexible_device_sensors()
    context_sensors = {
        field: Sensor.query.get(asset.flex_context[field]["sensor"])
        for field in asset.flex_context
        if isinstance(asset.flex_context[field], dict)
        and field != "inflexible-device-sensors"
    }
    sensors = []
    for sensor_status in sensor_statuses:
        sensor_status["id"] = sensor.id
        sensor_status["name"] = sensor.name
        sensor_status["resolution"] = naturaldelta(sensor.event_resolution)
        sensor_status["staleness"] = (
            naturaldelta(sensor_status["staleness"])
            if sensor_status["staleness"] is not None
            else None
        )
        sensor_status["staleness_since"] = (
            naturaldelta(sensor_status["staleness_since"])
            if sensor_status["staleness_since"] is not None
            else None
        )
        sensor_status["asset_name"] = asset.name
        sensor_status["relation"] = _get_sensor_asset_relation(
            asset, sensor, inflexible_device_sensors, context_sensors
        )
        sensors.append(sensor_status)

    return sensors


def build_asset_jobs_data(
    asset: Asset,
) -> list[dict]:
    """Get all jobs data for an asset
    Returns a list of dictionaries, each containing the following keys:
    - job_id: id of a job
    - queue: job queue (scheduling or forecasting)
    - asset_or_sensor_type: type of an asset that is linked to the job (asset or sensor)
    - asset_id: id of sensor or asset
    - status: job status (e.g finished, failed, etc)
    - err: job error (equals to None when there was no error for a job)
    - enqueued_at: time when the job was enqueued
    - metadata_hash: hash of job metadata (internal field)
    """

    jobs = list()

    # try to get scheduling jobs for asset first (only scheduling jobs can be stored by asset id)
    jobs.append(
        (
            "scheduling",
            "asset",
            asset.id,
            asset.name,
            current_app.job_cache.get(asset.id, "scheduling", "asset"),
        )
    )

    for sensor in asset.sensors:
        jobs.append(
            (
                "scheduling",
                "sensor",
                sensor.id,
                sensor.name,
                current_app.job_cache.get(sensor.id, "scheduling", "sensor"),
            )
        )
        jobs.append(
            (
                "forecasting",
                "sensor",
                sensor.id,
                sensor.name,
                current_app.job_cache.get(sensor.id, "forecasting", "sensor"),
            )
        )

    jobs_data = list()
    # Building the actual return list - we also unpack lists of jobs, each to its own entry, and we add error info
    for queue, asset_or_sensor_type, entity_id, entity_name, jobs in jobs:
        for job in jobs:
            e = job.meta.get(
                "exception",
                Exception(
                    "The job does not state why it failed. "
                    "The worker may be missing an exception handler, "
                    "or its exception handler is not storing the exception as job meta data."
                ),
            )
            job_err = (
                f"Scheduling job failed with {type(e).__name__}: {e}"
                if job.is_failed
                else None
            )

            metadata = json.dumps({**job.meta, "job_id": job.id}, default=str, indent=4)
            jobs_data.append(
                {
                    "job_id": job.id,
                    "metadata": metadata,
                    "queue": queue,
                    "asset_or_sensor_type": asset_or_sensor_type,
                    "entity": f"{asset_or_sensor_type}: {entity_name} (Id: {entity_id})",
                    "status": job.get_status(),
                    "err": job_err,
                    "enqueued_at": job.enqueued_at,
                    "metadata_hash": hashlib.sha256(metadata.encode()).hexdigest(),
                }
            )

    return jobs_data


def _get_sensor_stats(
    sensor: Sensor,
    event_end_time: str,
    event_start_time: str,
    sort_keys: bool,
) -> dict:
    # parse incoming datetimes (or leave None)
    start_dt = pd.to_datetime(event_start_time) if event_start_time else None
    end_dt = pd.to_datetime(event_end_time) if event_end_time else None

    # Subquery for filtered aggregates
    subq = sa.select(
        TimedBelief.source_id,
        sa.func.max(TimedBelief.event_value).label("max_event_value"),
        sa.func.avg(TimedBelief.event_value).label("avg_event_value"),
        sa.func.sum(TimedBelief.event_value).label("sum_event_value"),
        sa.func.min(TimedBelief.event_value).label("min_event_value"),
    ).filter(
        TimedBelief.event_value != float("NaN"),
        TimedBelief.sensor_id == sensor.id,
    )

    # apply start/end filters if provided
    if start_dt:
        subq = subq.filter(TimedBelief.event_start >= start_dt)
    if end_dt:
        subq = subq.filter(TimedBelief.event_start < end_dt)

    subquery_for_filtered_aggregates = subq.group_by(TimedBelief.source_id).subquery()

    # build main query
    q = (
        sa.select(
            DataSource,
            sa.func.min(TimedBelief.event_start).label("min_event_start"),
            sa.func.max(TimedBelief.event_start).label("max_event_start"),
            sa.func.max(
                TimedBelief.event_start
                + sensor.event_resolution
                - TimedBelief.belief_horizon
            ).label("max_belief_time"),
            subquery_for_filtered_aggregates.c.min_event_value,
            subquery_for_filtered_aggregates.c.max_event_value,
            subquery_for_filtered_aggregates.c.avg_event_value,
            subquery_for_filtered_aggregates.c.sum_event_value,
            sa.func.count(TimedBelief.event_value).label("count_event_value"),
        )
        .select_from(TimedBelief)
        .join(DataSource, DataSource.id == TimedBelief.source_id)
        .join(
            subquery_for_filtered_aggregates,
            subquery_for_filtered_aggregates.c.source_id == TimedBelief.source_id,
        )
        .filter(TimedBelief.sensor_id == sensor.id)
    )

    # apply the same start/end filters to the main query
    if start_dt:
        q = q.filter(TimedBelief.event_start >= start_dt)
    if end_dt:
        q = q.filter(TimedBelief.event_start < end_dt)

    raw_stats = db.session.execute(
        q.group_by(
            DataSource.id,
            subquery_for_filtered_aggregates.c.min_event_value,
            subquery_for_filtered_aggregates.c.max_event_value,
            subquery_for_filtered_aggregates.c.avg_event_value,
            subquery_for_filtered_aggregates.c.sum_event_value,
        )
    ).fetchall()

    stats = dict()
    for row in raw_stats:
        (
            data_source_obj,
            min_event_start,
            max_event_start,
            max_belief_time,
            min_value,
            max_value,
            mean_value,
            sum_values,
            count_values,
        ) = row
        first_event_start = (
            pd.Timestamp(min_event_start).tz_convert(sensor.timezone).isoformat()
        )
        last_event_end = (
            pd.Timestamp(max_event_start + sensor.event_resolution)
            .tz_convert(sensor.timezone)
            .isoformat()
        )
        last_belief_time = (
            pd.Timestamp(max_belief_time).tz_convert(sensor.timezone).isoformat()
        )
        data_source = f"{data_source_obj.description} (ID: {data_source_obj.id})"
        stats[data_source] = {
            "First event start": first_event_start,
            "Last event end": last_event_end,
            "Last recorded": last_belief_time,
            "Min value": min_value,
            "Max value": max_value,
            "Mean value": mean_value,
            "Sum over values": sum_values,
            "Number of values": count_values,
        }
        if sort_keys is False:
            stats[data_source] = stats[data_source].items()
    return stats


# Per-key TTL cache for sensor stats.
#
# Design:
# - The key includes a 120-second time bucket (round(time.time() / TTL)) so
#   at most ONE DB hit per sensor per 120-second window is possible, even
#   under repeated requests.  This limits the attack surface for cache
#   exhaustion: a caller can generate at most one new key per sensor per
#   bucket period.
# - Empty results are never stored, so freshly-uploaded data is always
#   visible on the next call (at the cost of one DB hit per empty request).
# - The dict is capped at _SENSOR_STATS_MAX_SIZE entries; when full, the
#   oldest entry (FIFO insertion order, Python 3.7+) is evicted first.
#
# key:   (sensor_id, event_end_time, event_start_time, sort_keys, time_bucket)
# value: result dict (non-empty only)
_sensor_stats_cache: dict = {}
_SENSOR_STATS_TTL = 120  # seconds
_SENSOR_STATS_MAX_SIZE = 1000


def get_sensor_stats(
    sensor: Sensor, event_start_time: str, event_end_time: str, sort_keys: bool = True
) -> dict:
    """Get stats for a sensor.

    Non-empty results are cached per sensor for up to 120 seconds (one DB hit
    per 120-second time bucket).  Empty results are never cached so that data
    uploaded to a previously-empty sensor is visible immediately.
    """
    bucket = round(time.time() / _SENSOR_STATS_TTL)
    key = (sensor.id, event_end_time, event_start_time, sort_keys, bucket)

    if key in _sensor_stats_cache:
        return _sensor_stats_cache[key]

    result = _get_sensor_stats(sensor, event_end_time, event_start_time, sort_keys)

    # Only cache non-empty results to keep empty sensors always fresh.
    if result:
        if len(_sensor_stats_cache) >= _SENSOR_STATS_MAX_SIZE:
            # Evict the oldest entry (FIFO; dict preserves insertion order).
            _sensor_stats_cache.pop(next(iter(_sensor_stats_cache)))
        _sensor_stats_cache[key] = result

    return result


def delete_sensor(sensor: Sensor):
    """Delete a sensor and all its time series data.

    Does not commit the session.
    Cleans up sensor references in asset JSONB fields.
    Creates an audit log.
    """
    sensor_name = sensor.name
    cleanup_sensor_references_in_assets(sensor.id, sensor.name)
    db.session.execute(delete(TimedBelief).filter_by(sensor_id=sensor.id))
    AssetAuditLog.add_record(
        sensor.generic_asset, f"Deleted sensor '{sensor_name}': {sensor.id}"
    )
    db.session.execute(delete(Sensor).filter_by(id=sensor.id))
    current_app.logger.info("Deleted sensor '%s'." % sensor_name)
