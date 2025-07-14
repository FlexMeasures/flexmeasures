from __future__ import annotations

import json
import hashlib
from datetime import datetime, timedelta
from flask import current_app
from functools import lru_cache
from isodate import duration_isoformat
import time
from timely_beliefs import BeliefsDataFrame
import pandas as pd

from humanize.time import precisedelta
from humanize import naturaldelta

from flexmeasures.data.models.time_series import TimedBelief


import sqlalchemy as sa

from flexmeasures.data import db
from flexmeasures import Sensor, Account, Asset
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.schemas.reporting import StatusSchema
from flexmeasures.utils.time_utils import server_now


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
    For now we use 'demo script', 'user', 'forecaster', 'scheduler' and 'reporter' source types
    """
    bdfs_by_source = dict()
    for source_type in ("demo script", "user", "forecaster", "scheduler", "reporter"):
        bdf = TimedBelief.search(
            sensors=sensor,
            most_recent_events_only=True,
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


@lru_cache()
def _get_sensor_stats(
    sensor: Sensor,
    event_end_time: str,
    event_start_time: str,
    sort_keys: bool,
    ttl_hash=None,
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


def _get_ttl_hash(seconds=120) -> int:
    """Returns the same value within "seconds" time period
    Is needed to make LRU cache a TTL one
    (lru_cache is used when call arguments are the same,
    here we ensure that call arguments are the same in "seconds" period of time).
    """
    return round(time.time() / seconds)


def get_sensor_stats(
    sensor: Sensor, event_start_time: str, event_end_time: str, sort_keys: bool = True
) -> dict:
    """Get stats for a sensor"""
    return _get_sensor_stats(
        sensor, event_end_time, event_start_time, sort_keys, ttl_hash=_get_ttl_hash()
    )
