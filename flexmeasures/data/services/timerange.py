from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select

from flexmeasures.data import db
from flexmeasures.utils import time_utils


def get_timerange(sensor_ids: list[int]) -> tuple[datetime, datetime]:
    """Get the start and end of the least recent and most recent event, respectively.

    In case of no data, defaults to (now, now).
    """
    from flexmeasures.data.models.time_series import Sensor, TimedBelief

    least_recent_event_start_and_most_recent_event_end = db.session.execute(
        select(
            func.min(TimedBelief.event_start),
            func.max(TimedBelief.event_start + Sensor.event_resolution),
        )
        .select_from(TimedBelief)
        .join(Sensor, TimedBelief.sensor_id == Sensor.id)
        .filter(TimedBelief.sensor_id.in_(sensor_ids))
    ).one_or_none()
    if least_recent_event_start_and_most_recent_event_end == (None, None):
        # return now in case there is no data for any of the sensors
        now = time_utils.server_now()
        return now, now
    return least_recent_event_start_and_most_recent_event_end
