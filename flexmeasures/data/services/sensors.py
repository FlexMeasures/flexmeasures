from __future__ import annotations

import json
import hashlib
from datetime import datetime, timedelta
from flask import current_app
from functools import lru_cache
from isodate import duration_isoformat
import time
from timely_beliefs import BeliefsDataFrame

from humanize.time import naturaldelta

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
    if account is None:
        account_ids = []
    elif isinstance(account, list):
        account_ids = [account.id for account in account]
    else:
        account_ids = [account.id]
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


def _get_sensor_bdf(sensor: Sensor, staleness_search: dict) -> BeliefsDataFrame | None:
    """Get bdf for a given sensor with given search parameters."""
    bdf = TimedBelief.search(
        sensors=sensor,
        most_recent_events_only=True,
        **staleness_search,
    )
    if bdf.empty:
        return None
    return bdf


def get_most_recent_knowledge_time(
    sensor: Sensor, staleness_search: dict
) -> datetime | None:
    """Get the knowledge time of the sensor's most recent event.

    This knowledge time represents when you could have known about the event
    (specifically, when you could have formed an ex-post belief about it).
    """
    staleness_bdf = _get_sensor_bdf(sensor=sensor, staleness_search=staleness_search)
    return None if staleness_bdf is None else staleness_bdf.knowledge_times[-1]


def get_staleness(
    sensor: Sensor, staleness_search: dict, now: datetime
) -> timedelta | None:
    """Get the staleness of the sensor.

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
    beliefs_before = staleness_search.get("beliefs_before")
    if beliefs_before is not None:
        staleness_search["beliefs_before"] = min(beliefs_before, now)
    else:
        staleness_search["beliefs_before"] = now

    staleness_start_time = get_most_recent_knowledge_time(
        sensor=sensor, staleness_search=staleness_search
    )
    if staleness_start_time is not None:
        staleness = now - staleness_start_time
    else:
        staleness = None

    return staleness


def get_status_specs(sensor: Sensor) -> dict:
    """Get status specs from a given sensor."""

    # Check for explicitly defined status specs
    status_specs = sensor.attributes.get("status_specs")
    if status_specs is None:
        # Default to status specs for economical sensors with daily updates
        if sensor.knowledge_horizon_fnc == "x_days_ago_at_y_oclock":
            status_specs = {"staleness_search": {}, "max_staleness": "P1D"}
        else:
            # Default to status specs indicating staleness after knowledge time + 2 sensor resolutions
            status_specs = {
                "staleness_search": {},
                "max_staleness": duration_isoformat(sensor.event_resolution * 2),
            }
    return status_specs


def get_status(
    sensor: Sensor,
    now: datetime,
    status_specs: dict | None = None,
) -> dict:
    """Get the status of the sensor
    Main part of result here is a stale value, which is True if the sensor is stale, False otherwise.
    Other values are just context information for the stale value.
    """
    if status_specs is None:
        status_specs = get_status_specs(sensor=sensor)
    status_specs = StatusSchema().load(status_specs)
    max_staleness = status_specs.pop("max_staleness")
    staleness_search = status_specs.pop("staleness_search")
    staleness: timedelta = get_staleness(
        sensor=sensor,
        staleness_search=staleness_search,
        now=now,
    )
    if staleness is not None:
        staleness_since = now - staleness
        stale = staleness > max_staleness
        reason = (
            "" if stale else "not "
        ) + f"more than {naturaldelta(max_staleness)} old"
        staleness = staleness if staleness > timedelta(0) else -staleness
    else:
        staleness_since = None
        stale = True
        reason = "no data recorded"
    status = dict(
        staleness=staleness,
        stale=stale,
        staleness_since=staleness_since,
        reason=reason,
    )
    return status


def _get_sensor_asset_relation(
    asset: Asset,
    sensor: Sensor,
    inflexible_device_sensors: list[Sensor],
) -> str:
    """Get the relation of a sensor to an asset."""
    relations = list()
    if sensor.generic_asset_id == asset.id:
        relations.append("included device")
    if asset.consumption_price_sensor_id == sensor.id:
        relations.append("consumption price")
    if asset.production_price_sensor_id == sensor.id:
        relations.append("production price")
    inflexible_device_sensors_ids = {sensor.id for sensor in inflexible_device_sensors}
    if sensor.id in inflexible_device_sensors_ids:
        relations.append("inflexible device")

    return ";".join(relations)


def build_sensor_status_data(
    asset: Asset,
    now: datetime = None,
) -> list[dict]:
    """Get data connectivity status information for each sensor in given asset and its children
    Returns a list of dictionaries, each containing the following keys:
    - id: sensor id
    - name: sensor name
    - asset_name: asset name
    - staleness: staleness of the sensor (for how long the sensor data is stale)
    - stale: whether the sensor is stale
    - staleness_since: time since sensor data is considered stale
    - reason: reason for staleness
    - relation: relation of the sensor to the asset
    """
    if not now:
        now = server_now()

    sensors = []
    sensor_ids = set()
    production_price_sensor = asset.get_production_price_sensor()
    consumption_price_sensor = asset.get_consumption_price_sensor()
    inflexible_device_sensors = asset.get_inflexible_device_sensors()
    for asset, is_child_asset in (
        (asset, False),
        *[(child_asset, True) for child_asset in asset.child_assets],
    ):
        sensors_list = list(asset.sensors)
        if not is_child_asset:
            sensors_list += [
                *asset.inflexible_device_sensors,
                production_price_sensor,
                consumption_price_sensor,
            ]
        for sensor in sensors_list:
            if sensor is None or sensor.id in sensor_ids:
                continue
            sensor_status = get_status(
                sensor=sensor,
                now=now,
            )
            sensor_status["name"] = sensor.name
            sensor_status["id"] = sensor.id
            sensor_status["asset_name"] = sensor.generic_asset.name
            sensor_status["relation"] = _get_sensor_asset_relation(
                asset, sensor, inflexible_device_sensors
            )
            sensor_ids.add(sensor.id)
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
def _get_sensor_stats(sensor: Sensor, ttl_hash=None) -> dict:
    # Subquery for filtered aggregates
    subquery_for_filtered_aggregates = (
        sa.select(
            TimedBelief.source_id,
            sa.func.max(TimedBelief.event_value).label("max_event_value"),
            sa.func.avg(TimedBelief.event_value).label("avg_event_value"),
            sa.func.sum(TimedBelief.event_value).label("sum_event_value"),
            sa.func.min(TimedBelief.event_value).label("min_event_value"),
        )
        .filter(TimedBelief.event_value != float("NaN"))
        .filter(TimedBelief.sensor_id == sensor.id)
        .group_by(TimedBelief.source_id)
        .subquery()
    )

    raw_stats = db.session.execute(
        sa.select(
            DataSource.name,
            sa.func.min(TimedBelief.event_start).label("min_event_start"),
            sa.func.max(TimedBelief.event_start).label("max_event_start"),
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
        .group_by(
            DataSource.name,
            subquery_for_filtered_aggregates.c.min_event_value,
            subquery_for_filtered_aggregates.c.max_event_value,
            subquery_for_filtered_aggregates.c.avg_event_value,
            subquery_for_filtered_aggregates.c.sum_event_value,
        )
    ).fetchall()

    stats = dict()
    for row in raw_stats:
        (
            data_source,
            min_event_start,
            max_event_start,
            min_value,
            max_value,
            mean_value,
            sum_values,
            count_values,
        ) = row
        stats[data_source] = {
            "min_event_start": min_event_start,
            "max_event_start": max_event_start,
            "min_value": min_value,
            "max_value": max_value,
            "mean_value": mean_value,
            "sum_values": sum_values,
            "count_values": count_values,
        }
    return stats


def _get_ttl_hash(seconds=120) -> int:
    """Returns the same value within "seconds" time period
    Is needed to make LRU cache a TTL one
    (lru_cache is used when call arguments are the same,
    here we ensure that call arguments are the same in "seconds" period of time).
    """
    return round(time.time() / seconds)


def get_sensor_stats(sensor: Sensor) -> dict:
    """Get stats for a sensor"""
    return _get_sensor_stats(sensor, ttl_hash=_get_ttl_hash())
