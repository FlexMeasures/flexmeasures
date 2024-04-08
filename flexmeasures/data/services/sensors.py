from __future__ import annotations

from datetime import datetime, timedelta
from timely_beliefs import BeliefsDataFrame

from humanize.time import precisedelta

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


def _get_sensor_bdfs_by_source(
    sensor: Sensor, staleness_search: dict
) -> dict[str, BeliefsDataFrame] | None:
    """Get bdf split by source type for a given sensor with given search parameters.
    For now we use 'user', 'forecaster', 'scheduler' and 'reporter' source types
    """
    bdfs_by_source = dict()
    for source_type in ("user", "forecaster", "scheduler", "reporter"):
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
    For scheduler and forecaster sources staleness start is latest event start time.

    For other sources staleness start is the knowledge time of the sensor's most recent event.
    This knowledge time represents when you could have known about the event
    (specifically, when you could have formed an ex-post belief about it).
    """
    staleness_bdfs = _get_sensor_bdfs_by_source(
        sensor=sensor, staleness_search=staleness_search
    )
    if staleness_bdfs is None:
        return None

    start_times = dict()
    for source, bdf in staleness_bdfs.items():
        time_column = "knowledge_times"
        source = str(source)
        is_data_ok = True
        if source in ("scheduler", "forecaster"):
            # filter to get only future events
            bdf_filtered = bdf[bdf.event_starts > now]
            time_column = "event_starts"
            if bdf_filtered.empty:
                is_data_ok = False
                bdf_filtered = bdf
        start_times[source] = (
            is_data_ok,
            getattr(bdf_filtered, time_column)[-1] if not bdf_filtered.empty else None,
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
    for source, (is_data_ok, start_time) in staleness_start_times.items():
        stalenesses[str(source)] = (
            is_data_ok,
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
    else:
        # Default to status specs indicating immediate staleness after knowledge time
        status_specs["max_staleness"] = "PT0H"
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
    for source, (is_data_ok, staleness) in (
        stalenesses or {None: (True, None)}
    ).items():
        if staleness is None or not is_data_ok:
            staleness_since = now - staleness if not is_data_ok else None
            stale = True
            reason = "no data recorded" if staleness is None else "Found no future data"
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
                source=source,
            )
        )

    return statuses


def build_sensor_status_data(
    asset: Asset,
    now: datetime = None,
) -> list:
    """Get data connectivity status information for each sensor split by source in given asset and its children
    Returns a list of dictionaries, each containing the following keys:
    - id: sensor id
    - name: sensor name
    - asset_name: asset name
    - staleness: staleness of the sensor (for how long the sensor data is stale)
    - stale: whether the sensor is stale
    - staleness_since: time since sensor data is considered stale
    - reason: reason for staleness
    - source: source of the sensor data
    """
    if not now:
        now = server_now()

    sensors = []
    for asset in (asset, *asset.child_assets):
        for sensor in asset.sensors:
            sensor_statuses = get_statuses(
                sensor=sensor,
                now=now,
            )
            for sensor_status in sensor_statuses:
                sensor_status["name"] = sensor.name
                sensor_status["id"] = sensor.id
                sensor_status["asset_name"] = asset.name
                sensors.append(sensor_status)
    return sensors
