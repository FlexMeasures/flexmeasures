from __future__ import annotations

from datetime import datetime

from flexmeasures.utils import time_utils


def get_timerange(sensor_ids: list[int]) -> tuple[datetime, datetime]:
    """Get the start and end of the least recent and most recent event, respectively."""
    from flexmeasures.data.models.time_series import TimedBelief

    least_recent_query = (
        TimedBelief.query.filter(TimedBelief.sensor_id.in_(sensor_ids))
        .order_by(TimedBelief.event_start.asc())
        .limit(1)
    )
    most_recent_query = (
        TimedBelief.query.filter(TimedBelief.sensor_id.in_(sensor_ids))
        .order_by(TimedBelief.event_start.desc())
        .limit(1)
    )
    results = least_recent_query.union_all(most_recent_query).all()
    try:
        # try the most common case first (sensor has more than 1 data point)
        least_recent, most_recent = results
    except ValueError as e:
        if not results:
            # return now in case there is no data for any of the sensors
            now = time_utils.server_now()
            return now, now
        elif len(results) == 1:
            # return the start and end of the only data point found
            least_recent = most_recent = results[0]
        else:
            # reraise this unlikely error
            raise e

    return least_recent.event_start, most_recent.event_end
