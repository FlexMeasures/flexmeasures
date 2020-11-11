from datetime import datetime, timedelta
from typing import List, Union, Optional, Tuple

from flask import request, session, current_app
from flask_security.core import current_user
from humanize import naturaldate, naturaltime
from werkzeug.exceptions import BadRequest
import pandas as pd
from pandas.tseries.frequencies import to_offset
import iso8601
import pytz
import tzlocal
from dateutil import tz


def bvp_now() -> datetime:
    """The current time of the bvp platform. UTC time, localized to the bvp timezone."""
    return as_bvp_time(datetime.utcnow())


def ensure_korea_local(
    dt: Union[pd.Timestamp, datetime]
) -> Union[pd.Timestamp, datetime]:
    """If no timezone is given, assume the datetime is in Korean local time and make it explicit.
    Otherwise, if a timezone is given, convert to Korean time."""
    tz_name = "Asia/Seoul"
    if isinstance(dt, datetime):
        if dt.tzinfo is not None:
            return dt.astimezone(tz.gettz(tz_name))
        else:
            return dt.replace(tzinfo=tz.gettz(tz_name))
    if dt.tzinfo is not None:
        return dt.tz_convert(tz_name)
    else:
        return dt.tz_localize(tz_name)


def as_bvp_time(dt: datetime) -> datetime:
    """The datetime represented in the timezone of the bvp platform."""
    return naive_utc_from(dt).replace(tzinfo=pytz.utc).astimezone(get_timezone())


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


def localized_datetime(dt: datetime) -> datetime:
    """Localise a datetime to the timezone of the BVP platform."""
    return get_timezone().localize(naive_utc_from(dt))


def localized_datetime_str(dt: datetime, dt_format: str = "%Y-%m-%d %I:%M %p") -> str:
    """Localise a datetime to the timezone of the BVP platform.
    Hint: This can be set as a jinja filter, so we can display local time in the app, e.g.:
    app.jinja_env.filters['datetime'] = localized_datetime_filter
    If no datetime is passed in, use bvp_now() as basis.
    """
    if dt is None:
        dt = bvp_now()
    local_tz = get_timezone()
    local_dt = naive_utc_from(dt).astimezone(local_tz)
    return local_dt.strftime(dt_format)


def naturalized_datetime_str(dt: Optional[datetime]) -> str:
    """ Naturalise a datetime object."""
    if dt is None:
        return "never"
    # humanize uses the local now internally, so let's make dt local
    local_timezone = tzlocal.get_localzone()
    local_dt = (
        dt.replace(tzinfo=pytz.utc).astimezone(local_timezone).replace(tzinfo=None)
    )
    if dt >= datetime.utcnow() - timedelta(hours=24):
        return naturaltime(local_dt)
    else:
        return naturaldate(local_dt)


def decide_session_resolution(
    start: Optional[datetime], end: Optional[datetime]
) -> str:
    """Decide on a resolution for this session
    (for plotting and data queries),
    given the length of the selected time period."""
    if start is None or end is None:
        return "15T"  # default if we cannot tell period
    period_length = end - start
    if period_length > timedelta(weeks=16):
        resolution = "168h"  # So upon switching from days to weeks, you get at least 16 data points
    elif period_length > timedelta(days=14):
        resolution = "24h"  # So upon switching from hours to days, you get at least 14 data points
    elif period_length > timedelta(hours=48):
        resolution = "1h"  # So upon switching from 15min to hours, you get at least 48 data points
    elif period_length > timedelta(hours=8):
        resolution = "15T"
    else:
        resolution = "5T"  # we are not going lower than 5 minutes
    return resolution


def resolution_to_hour_factor(resolution: str):
    """Return the factor with which a value needs to be multiplied in order to get the value per hour,
    e.g. 10 MW at a resolution of 15min are 2.5 MWh per time step"""
    return pd.Timedelta(resolution).to_pytimedelta() / timedelta(hours=1)


def get_timezone(of_user=False):
    """Return the BVP timezone, or if desired try to return the timezone of the current user."""
    default_timezone = pytz.timezone(current_app.config.get("BVP_TIMEZONE"))
    if not of_user:
        return default_timezone
    if current_user.is_anonymous:
        return default_timezone
    if current_user.timezone not in pytz.common_timezones:
        return default_timezone
    return pytz.timezone(current_user.timezone)


def round_to_closest_quarter(dt: datetime) -> datetime:
    new_hour = dt.hour
    new_minute = 15 * round((float(dt.minute) + float(dt.second) / 60) / 15)
    if new_minute == 60:
        new_hour += 1
        new_minute = 0
    return datetime(dt.year, dt.month, dt.day, new_hour, new_minute, tzinfo=dt.tzinfo)


def round_to_closest_hour(dt: datetime) -> datetime:
    if dt.minute >= 30:
        return datetime(dt.year, dt.month, dt.day, dt.hour + 1, tzinfo=dt.tzinfo)
    else:
        return datetime(dt.year, dt.month, dt.day, dt.hour, tzinfo=dt.tzinfo)


def get_most_recent_quarter() -> datetime:
    now = bvp_now()
    return now.replace(minute=now.minute - (now.minute % 15), second=0, microsecond=0)


def get_most_recent_hour() -> datetime:
    now = bvp_now()
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
    else:
        if (
            session["start_time"].tzinfo is None
        ):  # session storage seems to lose tz info
            session["start_time"] = (
                session["start_time"]
                .replace(tzinfo=pytz.utc)
                .astimezone(get_timezone())
            )

    if "end_time" in request.values:
        session["end_time"] = localized_datetime(
            iso8601.parse_date(request.values.get("end_time"))
        )
    elif "end_time" not in session:
        session["end_time"] = get_default_end_time()
    else:
        if session["end_time"].tzinfo is None:
            session["end_time"] = (
                session["end_time"].replace(tzinfo=pytz.utc).astimezone(get_timezone())
            )

    # Our demo server works only with the current year's data
    if current_app.config.get("BVP_MODE", "") == "demo":
        session["start_time"] = session["start_time"].replace(year=datetime.now().year)
        session["end_time"] = session["end_time"].replace(year=datetime.now().year)
        if session["start_time"] >= session["end_time"]:
            session["start_time"], session["end_time"] = (
                session["end_time"],
                session["start_time"],
            )

    if session["start_time"] >= session["end_time"]:
        raise BadRequest(
            "Start time %s is not after end time %s."
            % (session["start_time"], session["end_time"])
        )

    session["resolution"] = decide_session_resolution(
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
    f2h_map = {
        "5T": "5 minutes",
        "15T": "15 minutes",
        "1h": "1 hour",
        "24h": "1 day",
        "168h": "1 week",
    }
    return f2h_map.get(freq_label, freq_label)


def forecast_horizons_for(
    resolution: Union[str, timedelta]
) -> Union[List[str], List[timedelta]]:
    """Return a list of horizons that are supported per resolution.
    Return values or of the same type as the input."""
    if isinstance(resolution, timedelta):
        resolution_str = timedelta_to_pandas_freq_str(resolution)
    else:
        resolution_str = resolution
    horizons = []
    if resolution_str in ("15T", "1h", "H"):
        horizons = ["1h", "6h", "24h", "48h"]
    elif resolution_str in ("24h", "D"):
        horizons = ["24h", "48h"]
    elif resolution_str in ("168h", "7D"):
        horizons = ["168h"]
    if isinstance(resolution, timedelta):
        return [pd.to_timedelta(to_offset(h)) for h in horizons]
    else:
        return horizons


def supported_horizons() -> List[timedelta]:
    return [
        timedelta(hours=1),
        timedelta(hours=6),
        timedelta(hours=24),
        timedelta(hours=48),
    ]


def timedelta_to_pandas_freq_str(resolution: timedelta) -> str:
    return to_offset(resolution).freqstr


def ensure_timing_vars_are_set(
    time_window: Tuple[Optional[datetime], Optional[datetime]],
    resolution: Optional[str],
) -> Tuple[Tuple[datetime, datetime], str]:
    start = time_window[0]
    end = time_window[-1]
    if None in (start, end, resolution):
        current_app.logger.warning("Setting time range for session.")
        set_time_range_for_session()
        start_out: datetime = session["start_time"]
        end_out: datetime = session["end_time"]
        resolution_out: str = session["resolution"]
    else:
        start_out = start  # type: ignore
        end_out = end  # type: ignore
        resolution_out = resolution  # type: ignore

    return (start_out, end_out), resolution_out
