from datetime import datetime, timedelta
from typing import List, Union

from flask import request, session, current_app
from flask_security.core import current_user
from humanize import naturaldate, naturaltime
from werkzeug.exceptions import BadRequest
import pandas as pd
import iso8601
import pytz
import tzlocal


def naive_utc_from(dt: datetime) -> datetime:
    """Return a naive datetime, that is localised to UTC if it has a timezone."""
    if not hasattr(dt, "tzinfo") or dt.tzinfo is None:
        # let's hope this is the UTC time you expect
        return dt
    else:
        return dt.astimezone(pytz.utc).replace(tzinfo=None)


def tz_index_naively(
    data: Union[pd.DataFrame, pd.Series, pd.DatetimeIndex]
) -> Union[pd.DataFrame, pd.Series, pd.DatetimeIndex]:
    """Turn any DatetimeIndex into a tz-naive one, then return. Useful for bokeh, for instance."""
    if isinstance(data, pd.DatetimeIndex):
        return data.tz_localize(tz=None)
    if hasattr(data, "index") and isinstance(data.index, pd.DatetimeIndex):
        # TODO: if index is already naive, don't
        data.index = data.index.tz_localize(tz=None)
    return data


def localized_datetime(dt: datetime = None) -> datetime:
    """Localise a datetime to the timezone of the BVP platform.
    If no datetime is passed in, use utcnow() as basis."""
    if dt is None:
        dt = datetime.utcnow()
    return get_timezone().localize(naive_utc_from(dt))


def localized_datetime_str(dt: datetime, dt_format: str = "%Y-%m-%d %I:%M %p") -> str:
    """Localise a datetime to the timezone of the BVP platform.
       Hint: This can be set as a jinja filter, so we can display local time in the app, e.g.:
       app.jinja_env.filters['datetime'] = localized_datetime_filter
    """
    if dt is None:
        return ""
    local_tz = get_timezone()
    local_dt = naive_utc_from(dt).astimezone(local_tz)
    return local_dt.strftime(dt_format)


def naturalized_datetime_str(dt: datetime) -> str:
    """ Naturalise a datetime object."""
    # humanize uses the local now internally, so let's make dt local
    local_timezone = tzlocal.get_localzone()
    local_dt = (
        dt.replace(tzinfo=pytz.utc).astimezone(local_timezone).replace(tzinfo=None)
    )
    if dt >= datetime.utcnow() - timedelta(hours=24):
        return naturaltime(local_dt)
    else:
        return naturaldate(local_dt)


def decide_resolution(start: datetime, end: datetime) -> str:
    """Decide on a resolution, given the length of the time period."""
    resolution = "15T"  # default is 15 minute intervals
    period_length = end - start
    if period_length > timedelta(weeks=16):
        resolution = (
            "1w"
        )  # So upon switching from days to weeks, you get at least 16 data points
    elif period_length > timedelta(days=14):
        resolution = (
            "1d"
        )  # So upon switching from hours to days, you get at least 14 data points
    elif period_length > timedelta(hours=48):
        resolution = (
            "1h"
        )  # So upon switching from 15min to hours, you get at least 48 data points
    return resolution


def resolution_to_hour_factor(resolution: str):
    """Return the factor with which a value needs to be multiplied in order to get the value per hour,
    e.g. 10 MW at a resolution of 15min are 2.5 MWh per time step"""
    switch = {"15T": 0.25, "1h": 1, "1d": 24, "1w": 24 * 7}
    return switch.get(resolution, 1)


def get_timezone(of_user=False):
    """Get a timezone to be used, preferrably that of the current user."""
    default_timezone = pytz.timezone(current_app.config.get("BVP_TIMEZONE"))
    if not of_user:
        return default_timezone
    if current_user.is_anonymous:
        return default_timezone
    if current_user.timezone not in pytz.common_timezones:
        return default_timezone
    return pytz.timezone(current_user.timezone)


def get_most_recent_quarter() -> datetime:
    now = get_timezone().localize(datetime.now())
    return now.replace(minute=now.minute - (now.minute % 15), second=0, microsecond=0)


def get_most_recent_hour() -> datetime:
    now = get_timezone().localize(datetime.now())
    return now.replace(minute=now.minute - (now.minute % 60), second=0, microsecond=0)


def get_default_start_time() -> datetime:
    return get_most_recent_quarter() - timedelta(days=1)


def get_default_end_time() -> datetime:
    return get_most_recent_quarter() + timedelta(days=1)


def set_time_range_for_session():
    """Set period (start_date, end_date and resolution) on session if they are not yet set.
    Also set the forecast horizon, if given."""
    if "start_time" in request.values:
        session["start_time"] = localized_datetime(
            iso8601.parse_date(request.values.get("start_time"))
        )
    elif "start_time" not in session:
        session["start_time"] = get_default_start_time()
    if "end_time" in request.values:
        session["end_time"] = localized_datetime(
            iso8601.parse_date(request.values.get("end_time"))
        )
    elif "end_time" not in session:
        session["end_time"] = get_default_end_time()

    # TODO: For now, we have to work with the data we have, that means 2015
    session["start_time"] = session["start_time"].replace(year=2015)
    session["end_time"] = session["end_time"].replace(year=2015)

    if session["start_time"] >= session["end_time"]:
        raise BadRequest(
            "Start time %s is not after end time %s."
            % (session["start_time"], session["end_time"])
        )

    session["resolution"] = decide_resolution(
        session["start_time"], session["end_time"]
    )

    if "forecast_horizon" in request.values:
        session["forecast_horizon"] = request.values.get("forecast_horizon")
    allowed_horizons = forecast_horizons_for(session["resolution"])
    if (
        session.get("forecast_horizon") not in allowed_horizons
        and len(allowed_horizons) > 0
    ):
        session["forecast_horizon"] = allowed_horizons[0]


def freq_label_to_human_readable_label(freq_label: str) -> str:
    """Translate pandas frequency labels to human-readable labels."""
    f2h_map = {"15T": "15 minutes", "1h": "hour", "1d": "day", "1w": "week"}
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
