from __future__ import annotations

from datetime import datetime, timedelta
from flask import current_app
from timely_beliefs import BeliefsDataFrame

from humanize.time import naturaldelta

from flexmeasures.data.models.time_series import TimedBelief


import sqlalchemy as sa

from flexmeasures.data import db
from flexmeasures import Sensor, Account, Asset
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
    sensor_query = sensor_query.join(GenericAsset).filter(
        Sensor.generic_asset_id == GenericAsset.id
    )
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
            # Default to status specs indicating immediate staleness after knowledge time
            status_specs = {"staleness_search": {}, "max_staleness": "PT0H"}
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
    """
    if not now:
        now = server_now()

    sensors = []
    for asset in (asset, *asset.child_assets):
        for sensor in asset.sensors:
            sensor_status = get_status(
                sensor=sensor,
                now=now,
            )
            sensor_status["name"] = sensor.name
            sensor_status["id"] = sensor.id
            sensor_status["asset_name"] = asset.name
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
    """

    jobs = list()

    # try to get scheduling jobs for asset first (only scheduling jobs can be stored by asset id)
    jobs.append(
        (
            "scheduling",
            "asset",
            asset.id,
            current_app.job_cache.get(asset.id, "scheduling", "asset"),
        )
    )

    for sensor in asset.sensors:
        jobs.append(
            (
                "scheduling",
                "sensor",
                sensor.id,
                current_app.job_cache.get(sensor.id, "scheduling", "sensor"),
            )
        )
        jobs.append(
            (
                "forecasting",
                "sensor",
                sensor.id,
                current_app.job_cache.get(sensor.id, "forecasting", "sensor"),
            )
        )

    jobs_data = list()
    # Building the actual return list - we also unpack lists of jobs, each to its own entry, and we add error info
    for queue, asset_or_sensor_type, asset_id, jobs in jobs:
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

            jobs_data.append(
                {
                    "job_id": job.id,
                    "queue": queue,
                    "asset_or_sensor_type": asset_or_sensor_type,
                    "asset_id": asset_id,
                    "status": job.get_status(),
                    "err": job_err,
                    "enqueued_at": job.enqueued_at,
                }
            )

    return jobs_data
