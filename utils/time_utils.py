from datetime import datetime, timedelta
from typing import List

from flask import request, session
from werkzeug.exceptions import BadRequest
import iso8601


def decide_resolution(start: datetime, end: datetime) -> str:
    """Decide on a resolution, given the length of the time period."""
    resolution = "15T"  # default is 15 minute intervals
    period_length = end - start
    if period_length > timedelta(weeks=16):
        resolution = "1w"  # So upon switching from days to weeks, you get at least 16 data points
    elif period_length > timedelta(days=14):
        resolution = "1d"  # So upon switching from hours to days, you get at least 14 data points
    elif period_length > timedelta(hours=48):
        resolution = "1h"  # So upon switching from 15min to hours, you get at least 48 data points
    return resolution


def resolution_to_hour_factor(resolution: str):
    """Return the factor with which a value needs to be multiplied in order to get the value per hour,
    e.g. 10 MW at a resolution of 15min are 2.5 MWh per time step"""
    switch = {
        "15T": 0.25,
        "1h": 1,
        "1d": 24,
        "1w": 24 * 7
    }
    return switch.get(resolution, 1)


def get_most_recent_quarter() -> datetime:
    now = datetime.now()
    return now.replace(minute=now.minute - (now.minute % 15), second=0, microsecond=0)


def get_most_recent_hour() -> datetime:
    now = datetime.now()
    return now.replace(minute=now.minute - (now.minute % 60), second=0, microsecond=0)


def get_default_start_time() -> datetime:
    return get_most_recent_quarter() - timedelta(days=1)


def get_default_end_time() -> datetime:
    return get_most_recent_quarter() + timedelta(days=1)


def set_time_range_for_session():
    """Set period (start_date, end_date and resolution) on session if they are not yet set.
    Also set the forecast horizon, if given."""
    if "start_time" in request.values:
        session["start_time"] = iso8601.parse_date(request.values.get("start_time"))
    elif "start_time" not in session:
        session["start_time"] = get_default_start_time()
    if "end_time" in request.values:
        session["end_time"] = iso8601.parse_date(request.values.get("end_time"))
    elif "end_time" not in session:
        session["end_time"] = get_default_end_time()

    # TODO: For now, we have to work with the data we have, that means 2015
    session["start_time"] = session["start_time"].replace(year=2015)
    session["end_time"] = session["end_time"].replace(year=2015)

    if session["start_time"] >= session["end_time"]:
        raise BadRequest("Start time %s is not after end time %s." % (session["start_time"], session["end_time"]))

    session["resolution"] = decide_resolution(session["start_time"], session["end_time"])

    if "forecast_horizon" in request.values:
        session["forecast_horizon"] = request.values.get("forecast_horizon")
    allowed_horizons = forecast_horizons_for(session["resolution"])
    if session.get("forecast_horizon") not in allowed_horizons and len(allowed_horizons) > 0:
        session["forecast_horizon"] = allowed_horizons[0]


def freq_label_to_human_readable_label(freq_label: str) -> str:
    """Translate pandas frequency labels to human-readable labels."""
    f2h_map = {
        "15T": "15 minutes",
        "1h": "hour",
        "1d": "day",
        "1w": "week"
    }
    return f2h_map.get(freq_label, freq_label)


def forecast_horizons_for(resolution: str) -> List[str]:
    """Return a list of horizons that are supported per resolution."""
    if resolution in ("15T", "1h"):
        return ["6h", "48h"]
    elif resolution == "1d":
        return ["48h"]
    elif resolution == "1w":
        return ["1w"]
    return []
