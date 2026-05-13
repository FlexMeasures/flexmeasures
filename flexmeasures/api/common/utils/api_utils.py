from __future__ import annotations

from copy import deepcopy
import json
import re
from timely_beliefs.beliefs.classes import BeliefsDataFrame
from timely_beliefs.sensors.func_store import knowledge_horizons
from typing import Sequence
from datetime import timedelta

from flask import current_app
from werkzeug.exceptions import Forbidden, Unauthorized
from numpy import array
from psycopg2.errors import UniqueViolation
from rq import Worker
from rq.job import Job, JobStatus, NoSuchJobError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from flexmeasures.data import db
from flexmeasures.data.models.audit_log import AssetAuditLog
from flexmeasures.data.models.user import Account
from flexmeasures.data.services.data_ingestion import (
    add_beliefs_to_db_and_enqueue_forecasting_jobs,
)
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.auth.policy import check_access
from flexmeasures.api.common.responses import (
    invalid_replacement,
    ResponseTuple,
    request_processed,
    request_accepted_for_processing,
    already_received_and_successfully_processed,
)
from flexmeasures.data.schemas.generic_assets import GenericAssetSchema as AssetSchema
from flexmeasures.utils.error_utils import error_handling_router
from flexmeasures.utils.flexmeasures_inflection import capitalize


def upsample_values(
    value_groups: list[list[float]] | list[float],
    from_resolution: timedelta,
    to_resolution: timedelta,
) -> list[list[float]] | list[float]:
    """Upsample the values (in value groups) to a smaller resolution.
    from_resolution has to be a multiple of to_resolution"""
    if from_resolution % to_resolution == timedelta(hours=0):
        n = from_resolution // to_resolution
        if isinstance(value_groups[0], list):
            value_groups = [
                list(array(value_group).repeat(n)) for value_group in value_groups
            ]
        else:
            value_groups = list(array(value_groups).repeat(n))
    return value_groups


def unique_ever_seen(iterable: Sequence, selector: Sequence):
    """
    Return unique iterable elements with corresponding lists of selector elements, preserving order.

    >>> a, b = unique_ever_seen([[10, 20], [10, 20], [20, 40]], [1, 2, 3])
    >>> print(a)
    [[10, 20], [20, 40]]
    >>> print(b)
    [[1, 2], 3]
    """
    u = []
    s = []
    for iterable_element, selector_element in zip(iterable, selector):
        if iterable_element not in u:
            u.append(iterable_element)
            s.append(selector_element)
        else:
            us = s[u.index(iterable_element)]
            if not isinstance(us, list):
                us = [us]
            us.append(selector_element)
            s[u.index(iterable_element)] = us
    return u, s


def job_status_description(job: Job, extra_message: str | None = None):
    """Return a matching description for the job's status.

    Supports each rq.job.JobStatus (NB JobStatus.CREATED is deprecated).

    :param job:             The rq.Job.
    :param extra_message:   Optionally, append a message to the job status description.
    """

    job_status = job.get_status()
    queue_name = job.origin  # Name of the queue that the job is in
    if job_status == JobStatus.QUEUED:
        description = f"{capitalize(queue_name)} job waiting to be processed."
    elif job_status == JobStatus.FINISHED:
        description = f"{capitalize(queue_name)} job has finished."
    elif job_status == JobStatus.FAILED:
        # Try to inform the user on why the job failed
        e = job.meta.get(
            "exception",
            Exception(
                "The job does not state why it failed. "
                "The worker may be missing an exception handler, "
                "or its exception handler is not storing the exception as job meta data."
            ),
        )
        description = (
            f"{capitalize(queue_name)} job failed with {type(e).__name__}: {e}."
        )
    elif job_status == JobStatus.STARTED:
        description = f"{capitalize(queue_name)} job in progress."
    elif job_status == JobStatus.DEFERRED:
        # Try to inform the user on what other job the job is waiting for
        try:
            preferred_job = job.dependency
            description = f'{capitalize(queue_name)} job waiting for {preferred_job.status} job "{preferred_job.id}" to be processed.'
        except NoSuchJobError:
            description = (
                f"{capitalize(queue_name)} job waiting for unknown job to be processed."
            )
    elif job_status == JobStatus.SCHEDULED:
        description = (
            f"{capitalize(queue_name)} job is scheduled to run at a later time."
        )
    elif job_status == JobStatus.STOPPED:
        description = f"{capitalize(queue_name)} job has been stopped."
    elif job_status == JobStatus.CANCELED:
        description = f"{capitalize(queue_name)} job has been cancelled."
    else:
        description = f"{capitalize(queue_name)} job has an unknown status."

    return description + f" {extra_message}" if extra_message else description


def enqueue_forecasting_jobs(
    forecasting_jobs: list[Job] | None = None,
):
    """Enqueue forecasting jobs.

    :param forecasting_jobs: list of forecasting Jobs for redis queues.
    """
    if forecasting_jobs is not None:
        [current_app.queues["forecasting"].enqueue_job(job) for job in forecasting_jobs]


def save_and_enqueue(
    data: BeliefsDataFrame | list[BeliefsDataFrame],
    forecasting_jobs: list[Job] | None = None,
    save_changed_beliefs_only: bool = True,
) -> ResponseTuple:
    status = add_beliefs_to_db_and_enqueue_forecasting_jobs(
        data,
        forecasting_jobs=forecasting_jobs,
        save_changed_beliefs_only=save_changed_beliefs_only,
    )

    # Pick a response
    if status == "success":
        return request_processed()
    elif status in (
        "success_with_unchanged_beliefs_skipped",
        "success_but_nothing_new",
    ):
        return already_received_and_successfully_processed()
    return invalid_replacement()


def enqueue_sensor_data_ingestion(
    sensor_id: int,
    user_id: int,
    sensor_data: dict | None = None,
    uploaded_files: list[dict] | None = None,
    upload_data: dict | None = None,
    forecasting_jobs: list[Job] | None = None,
    save_changed_beliefs_only: bool = True,
) -> ResponseTuple:
    ingestion_queue = current_app.queues.get("ingestion")
    if ingestion_queue is None:
        current_app.logger.warning(
            "No ingestion queue configured. Processing sensor data directly."
        )
    else:
        workers = Worker.all(queue=ingestion_queue)
        if workers:
            forecasting_job_ids = (
                [job.id for job in forecasting_jobs]
                if forecasting_jobs is not None
                else None
            )
            job = ingestion_queue.enqueue(
                add_beliefs_to_db_and_enqueue_forecasting_jobs,
                sensor_id=sensor_id,
                user_id=user_id,
                sensor_data=sensor_data,
                uploaded_files=uploaded_files,
                upload_data=upload_data,
                forecasting_job_ids=forecasting_job_ids,
                save_changed_beliefs_only=save_changed_beliefs_only,
                meta={"sensor_id": sensor_id},
            )
            return request_accepted_for_processing(
                job.id,
                "Sensor data has been accepted for processing.",
            )
        else:
            current_app.logger.warning(
                "No workers connected to the ingestion queue. Processing sensor data directly."
            )

    status = add_beliefs_to_db_and_enqueue_forecasting_jobs(
        sensor_id=sensor_id,
        user_id=user_id,
        sensor_data=sensor_data,
        uploaded_files=uploaded_files,
        upload_data=upload_data,
        forecasting_jobs=forecasting_jobs,
        save_changed_beliefs_only=save_changed_beliefs_only,
    )

    if status == "success":
        return request_processed()
    elif status in (
        "success_with_unchanged_beliefs_skipped",
        "success_but_nothing_new",
    ):
        return already_received_and_successfully_processed()
    return invalid_replacement()


def catch_timed_belief_replacements(error: IntegrityError):
    """Catch IntegrityErrors due to a UniqueViolation on the TimedBelief primary key.

    Return a more informative message.
    """
    if isinstance(error.orig, UniqueViolation) and "timed_belief_pkey" in str(
        error.orig
    ):
        # Some beliefs represented replacements, which was forbidden
        return invalid_replacement()

    # Forward to our generic error handler
    return error_handling_router(error)


def get_accessible_accounts() -> list[Account]:
    accounts = []
    for _account in db.session.scalars(select(Account)).all():
        try:
            check_access(_account, "read")
            accounts.append(_account)
        except (Forbidden, Unauthorized):
            pass

    return accounts


def convert_asset_json_fields(asset_kwargs):
    """
    Convert string fields in asset_kwargs to JSON where needed.
    """
    if "attributes" in asset_kwargs and isinstance(asset_kwargs["attributes"], str):
        asset_kwargs["attributes"] = json.loads(asset_kwargs["attributes"])
    if "sensors_to_show" in asset_kwargs and isinstance(
        asset_kwargs["sensors_to_show"], str
    ):
        asset_kwargs["sensors_to_show"] = json.loads(asset_kwargs["sensors_to_show"])
    if "flex_context" in asset_kwargs and isinstance(asset_kwargs["flex_context"], str):
        asset_kwargs["flex_context"] = json.loads(asset_kwargs["flex_context"])
    if "flex_model" in asset_kwargs and isinstance(asset_kwargs["flex_model"], str):
        asset_kwargs["flex_model"] = json.loads(asset_kwargs["flex_model"])
    if "sensors_to_show_as_kpis" in asset_kwargs and isinstance(
        asset_kwargs["sensors_to_show_as_kpis"], str
    ):
        asset_kwargs["sensors_to_show_as_kpis"] = json.loads(
            asset_kwargs["sensors_to_show_as_kpis"]
        )
    return asset_kwargs


def _copy_direct_sensors(
    source_asset: GenericAsset, copied_asset: GenericAsset
) -> dict[int, int]:
    """Copy sensors directly attached to one asset.

    Returns a mapping of original sensor ID → new sensor ID for every sensor copied.
    """
    sensor_id_map: dict[int, int] = {}
    source_sensors = db.session.scalars(
        select(Sensor).filter(Sensor.generic_asset_id == source_asset.id)
    ).all()
    for source_sensor in source_sensors:
        sensor_kwargs = {}
        for column in source_sensor.__table__.columns:
            if column.name in [
                "id",
                "generic_asset_id",
                "knowledge_horizon_fnc",
                "knowledge_horizon_par",
            ]:
                continue
            sensor_kwargs[column.name] = deepcopy(getattr(source_sensor, column.name))

        sensor_kwargs["generic_asset_id"] = copied_asset.id
        # Reconstruct knowledge_horizon tuple with actual function object
        # (stored in DB as function name string, but Sensor constructor expects function object)
        knowledge_horizon_fnc = getattr(
            knowledge_horizons, source_sensor.knowledge_horizon_fnc
        )
        sensor_kwargs["knowledge_horizon"] = (
            knowledge_horizon_fnc,
            deepcopy(source_sensor.knowledge_horizon_par),
        )

        new_sensor = Sensor(**sensor_kwargs)
        db.session.add(new_sensor)
        db.session.flush()  # obtain new_sensor.id
        sensor_id_map[source_sensor.id] = new_sensor.id

    return sensor_id_map


# Sentinel returned by _replace_sensor_refs to signal that a containing entry
# should be omitted entirely (used when a sensor reference points to a private
# asset that is neither public nor part of the copied subtree).
_REMOVED = object()


def _is_sensor_on_public_asset(sensor_id: int) -> bool:
    """Return True if *sensor_id* belongs to a public asset (account_id is None).

    Unknown sensor IDs are treated as private (returns False) so that stale
    references are also cleaned up during the copy.
    """
    sensor = db.session.get(Sensor, sensor_id)
    if sensor is None:
        return False
    asset = db.session.get(GenericAsset, sensor.generic_asset_id)
    return asset is not None and asset.account_id is None


def _resolve_sensor_id(sensor_id: int, sensor_id_map: dict[int, int]) -> int | object:
    """Resolve a single sensor ID during an asset copy.

    Returns:

    * The new sensor ID if the sensor was copied (*sensor_id* is in *sensor_id_map*).
    * The original sensor ID if the sensor belongs to a public asset.
    * :data:`_REMOVED` sentinel if the sensor is on a private external asset.
    """
    if sensor_id in sensor_id_map:
        return sensor_id_map[sensor_id]
    if _is_sensor_on_public_asset(sensor_id):
        return sensor_id
    return _REMOVED


def _replace_sensor_refs(data, sensor_id_map: dict[int, int]):
    """Recursively replace sensor IDs inside a nested JSON structure.

    Handles the two reference patterns used in flex_context, flex_model and
    sensors_to_show:

    * ``{"sensor": <id>}``          – single sensor reference
    * ``{"sensors": [<id>, ...]}``  – list of sensor IDs

    For each sensor ID encountered:

    * If the ID is in *sensor_id_map* (sensor was copied) → replace with the new ID.
    * If the sensor belongs to a **public** asset (``account_id`` is ``None``) →
      keep the original ID as-is (publicly accessible, safe to reference).
    * Otherwise (sensor on a private asset not in the copied subtree) →
      the containing ``{"sensor": id}`` dict is dropped (returns :data:`_REMOVED`)
      and plain integer IDs in ``{"sensors": [...]}`` lists are filtered out.
    """

    if isinstance(data, dict):
        return _replace_sensor_refs_in_dict(data, sensor_id_map)
    if isinstance(data, list):
        # Update the ids in the list with the new ones, except for sensors from public assets, which are kept as is.
        return [
            (
                _resolve_sensor_id(sensor_id, sensor_id_map)
                if isinstance(sensor_id, int)
                else _replace_sensor_refs(sensor_id, sensor_id_map)
            )
            for sensor_id in data
        ]
    return data


def _replace_sensor_refs_in_dict(data: dict, sensor_id_map: dict[int, int]):
    """Handle the dict case for :func:`_replace_sensor_refs`."""
    result: dict = {}
    for key, value in data.items():
        if key == "sensor" and isinstance(value, int):
            resolved = _resolve_sensor_id(value, sensor_id_map)
            if resolved is _REMOVED:
                # Private external sensor: signal parent to drop this entry.
                return _REMOVED
            result[key] = resolved
        elif key == "sensors" and isinstance(value, list):
            result[key] = _replace_sensors_list(value, sensor_id_map)
        else:
            processed = _replace_sensor_refs(value, sensor_id_map)
            if processed is not _REMOVED:
                result[key] = processed
            # else: drop this key entirely
    return result


def _replace_sensors_list(value: list, sensor_id_map: dict[int, int]) -> list:
    """Replace/filter integer IDs in a ``{"sensors": [...]}`` list."""
    new_list = []
    for v in value:
        if not isinstance(v, int):
            new_list.append(v)
            continue
        resolved = _resolve_sensor_id(v, sensor_id_map)
        if resolved is not _REMOVED:
            new_list.append(resolved)
        # else: private external sensor, skip
    return new_list


def _update_sensor_refs_in_subtree(
    asset: GenericAsset, sensor_id_map: dict[int, int]
) -> None:
    """Update sensor references in flex_context, flex_model and sensors_to_show
    for the given asset and all its descendants.

    Sensor references that were copied are replaced with their new IDs.
    References to public (account_id = None) sensors are kept unchanged.
    References to private external sensors are removed.
    """
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
    destination_account_id: int,
    destination_parent_asset_id: int | None,
    asset_schema: AssetSchema,
    add_copy_suffix: bool,
) -> tuple[GenericAsset, dict[int, int]]:
    """Recursively copy one asset and all descendants.

    Returns a tuple of (copied_asset, sensor_id_map) where sensor_id_map maps
    every original sensor ID in the entire subtree to the corresponding new ID.
    """
    asset_kwargs = asset_schema.dump(source_asset)

    for key in ["id", "owner", "generic_asset_type", "child_assets", "sensors"]:
        asset_kwargs.pop(key, None)

    if add_copy_suffix:
        asset_kwargs["name"] = _determine_copy_name(
            source_name=asset_kwargs["name"],
            destination_account_id=destination_account_id,
            destination_parent_asset_id=destination_parent_asset_id,
        )
    asset_kwargs["account_id"] = destination_account_id
    asset_kwargs["parent_asset_id"] = destination_parent_asset_id
    asset_kwargs = convert_asset_json_fields(asset_kwargs)

    copied_asset = GenericAsset(**asset_kwargs)
    db.session.add(copied_asset)
    db.session.flush()

    sensor_id_map = _copy_direct_sensors(source_asset, copied_asset)

    source_children = db.session.scalars(
        select(GenericAsset)
        .filter(GenericAsset.parent_asset_id == source_asset.id)
        .order_by(GenericAsset.id)
    ).all()
    for source_child in source_children:
        _, child_sensor_map = _copy_asset_subtree(
            source_asset=source_child,
            destination_account_id=destination_account_id,
            destination_parent_asset_id=copied_asset.id,
            asset_schema=asset_schema,
            add_copy_suffix=False,
        )
        sensor_id_map.update(child_sensor_map)

    return copied_asset, sensor_id_map


def _determine_copy_name(
    source_name: str,
    destination_account_id: int,
    destination_parent_asset_id: int | None,
) -> str:
    """Return the next available copy name for the destination context.

    Examples: ``Home (Copy)``, ``Home (Copy 2)``, ``Home (Copy 3)``.
    """
    if destination_parent_asset_id is None:
        existing_names = set(
            db.session.scalars(
                select(GenericAsset.name).filter(
                    GenericAsset.parent_asset_id.is_(None),
                    GenericAsset.account_id == destination_account_id,
                )
            ).all()
        )
    else:
        existing_names = set(
            db.session.scalars(
                select(GenericAsset.name).filter(
                    GenericAsset.parent_asset_id == destination_parent_asset_id,
                )
            ).all()
        )

    first_copy_name = f"{source_name} (Copy)"
    if first_copy_name not in existing_names:
        return first_copy_name

    copy_name_pattern = re.compile(
        rf"^{re.escape(source_name)} \(Copy(?: (?P<index>\d+))?\)$"
    )
    max_index = 1
    for existing_name in existing_names:
        match = copy_name_pattern.match(existing_name)
        if not match:
            continue
        index = match.group("index")
        copy_index = int(index) if index is not None else 1
        if copy_index > max_index:
            max_index = copy_index

    return f"{source_name} (Copy {max_index + 1})"


def _asset_is_in_subtree(root_asset_id: int, candidate_asset_id: int) -> bool:
    """Return True if candidate_asset_id is root or a descendant of root_asset_id."""
    current_asset_id = candidate_asset_id
    visited: set[int] = set()

    while current_asset_id is not None and current_asset_id not in visited:
        if current_asset_id == root_asset_id:
            return True
        visited.add(current_asset_id)
        current_asset = db.session.get(GenericAsset, current_asset_id)
        if current_asset is None:
            return False
        current_asset_id = current_asset.parent_asset_id

    return False


def copy_asset(
    asset: GenericAsset,
    account=None,
    parent_asset=None,
) -> GenericAsset:
    """
    Copy an asset subtree to a target account and/or under a target parent asset.

    The copied subtree includes:
    - the selected asset
    - all descendant child assets (recursively)
    - all sensors directly attached to each copied asset

    Resolution rules:

    - If neither ``account`` nor ``parent_asset`` is given, the copy is placed in
      the same account and under the same parent as the original (i.e. a sibling).
    - If ``account`` is given but ``parent_asset`` is not, the copy becomes a
      top-level asset (no parent) in the given account.
    - If ``parent_asset`` is given but ``account`` is not, the copy is placed under
      the given parent and inherits that parent's account.
    - If both are given, the copy belongs to the given account and is placed under
      the given parent. This allows creating a copy that belongs to a different
      account than its parent.
    """
    try:
        asset_schema = AssetSchema()

        if account is None and parent_asset is None:
            target_account_id = int(asset.account_id)
            target_parent_asset_id = asset.parent_asset_id
        elif account is not None and parent_asset is None:
            target_account_id = int(account.id)
            target_parent_asset_id = None
        elif account is None and parent_asset is not None:
            target_account_id = int(parent_asset.account_id)
            target_parent_asset_id = int(parent_asset.id)
        else:
            target_account_id = int(account.id)
            target_parent_asset_id = int(parent_asset.id)

        if target_parent_asset_id is not None and _asset_is_in_subtree(
            root_asset_id=asset.id,
            candidate_asset_id=target_parent_asset_id,
        ):
            raise ValueError(
                "Invalid copy target parent: cannot copy an asset to itself or any of its descendants."
            )

        copied_root, sensor_id_map = _copy_asset_subtree(
            source_asset=asset,
            destination_account_id=target_account_id,
            destination_parent_asset_id=target_parent_asset_id,
            asset_schema=asset_schema,
            add_copy_suffix=True,
        )
        if sensor_id_map:
            _update_sensor_refs_in_subtree(copied_root, sensor_id_map)

        AssetAuditLog.add_record(
            copied_root,
            (
                f"Copied asset '{asset.name}': {asset.id} "
                f"to '{copied_root.name}': {copied_root.id}"
            ),
        )
        db.session.commit()
        return copied_root
    except Exception as e:
        db.session.rollback()
        raise e
