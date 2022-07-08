import re
from datetime import datetime, timedelta
from typing import List, Union, Tuple, Optional

from flask import current_app
from flask_security.core import current_user
from humanize import naturaldate, naturaltime
import pandas as pd
from pandas.tseries.frequencies import to_offset
import pytz
from dateutil import tz


def server_now() -> datetime:
    """The current time of the FlexMeasures platform. UTC time, localized to the FlexMeasures timezone."""
    return as_server_time(datetime.utcnow())


def ensure_local_timezone(
    dt: Union[pd.Timestamp, datetime], tz_name: str = "Europe/Amsterdam"
) -> Union[pd.Timestamp, datetime]:
    """If no timezone is given, assume the datetime is in the given timezone and make it explicit.
    Otherwise, if a timezone is given, convert to that timezone."""
    if isinstance(dt, datetime):
        if dt.tzinfo is not None:
            return dt.astimezone(tz.gettz(tz_name))
        else:
            return dt.replace(tzinfo=tz.gettz(tz_name))
    if dt.tzinfo is not None:
        return dt.tz_convert(tz_name)
    else:
        return dt.tz_localize(tz_name)


def as_server_time(dt: datetime) -> datetime:
    """The datetime represented in the timezone of the FlexMeasures platform.
    If dt is naive, we assume it is UTC time.
    """
    return naive_utc_from(dt).replace(tzinfo=pytz.utc).astimezone(get_timezone())


def localized_datetime(dt: datetime) -> datetime:
    """
    Localise a datetime to the timezone of the FlexMeasures platform.
    Note: this will change nothing but the tzinfo field.
    """
    return get_timezone().localize(naive_utc_from(dt))


def naive_utc_from(dt: datetime) -> datetime:
    """
    Return a naive datetime, that is localised to UTC if it has a timezone.
    If dt is naive, we assume it is already in UTC time.
    """
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


def localized_datetime_str(dt: datetime, dt_format: str = "%Y-%m-%d %I:%M %p") -> str:
    """
    Localise a datetime to the timezone of the FlexMeasures platform.
    If no datetime is passed in, use server_now() as basis.

    Hint: This can be set as a jinja filter, so we can display local time in the app, e.g.:
    app.jinja_env.filters['localized_datetime'] = localized_datetime_str
    """
    if dt is None:
        dt = server_now()
    local_tz = get_timezone()
    local_dt = naive_utc_from(dt).astimezone(local_tz)
    return local_dt.strftime(dt_format)


def naturalized_datetime_str(
    dt: Optional[datetime], now: Optional[datetime] = None
) -> str:
    """
    Naturalise a datetime object (into a human-friendly string).
    The dt parameter (as well as the now parameter if you use it)
    can be either naive or tz-aware. We assume UTC in the naive case.

    We use the the humanize library to generate a human-friendly string.
    If dt is not longer ago than 24 hours, we use humanize.naturaltime (e.g. "3 hours ago"),
    otherwise humanize.naturaldate (e.g. "one week ago")

    Hint: This can be set as a jinja filter, so we can display local time in the app, e.g.:
    app.jinja_env.filters['naturalized_datetime'] = naturalized_datetime_str
    """
    if dt is None:
        return "never"
    if now is None:
        now = datetime.utcnow()
    naive_utc_now = naive_utc_from(now)

    # Convert or localize to utc
    if dt.tzinfo is None:
        utc_dt = pd.Timestamp(dt).tz_localize("utc")
    else:
        utc_dt = pd.Timestamp(dt).tz_convert("utc")

    # decide which humanize call to use for naturalization
    if naive_utc_from(utc_dt) >= naive_utc_now - timedelta(hours=24):
        # return natural time (naive utc dt with respect to naive utc now)
        return naturaltime(
            utc_dt.replace(tzinfo=None),
            when=naive_utc_now,
        )
    else:
        # return natural date in the user's timezone
        local_dt = utc_dt.tz_convert(get_timezone(of_user=True))
        return naturaldate(local_dt)


def resolution_to_hour_factor(resolution: Union[str, timedelta]) -> float:
    """Return the factor with which a value needs to be multiplied in order to get the value per hour,
    e.g. 10 MW at a resolution of 15min are 2.5 MWh per time step.

    :param resolution: timedelta or pandas offset such as "15T" or "1H"
    """
    if isinstance(resolution, timedelta):
        return resolution / timedelta(hours=1)
    return pd.Timedelta(resolution).to_pytimedelta() / timedelta(hours=1)


def decide_resolution(start: Optional[datetime], end: Optional[datetime]) -> str:
    """
    Decide on a practical resolution given the length of the selected time period.
    Useful for querying or plotting.
    """
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
        resolution = "5T"  # we are (currently) not going lower than 5 minutes
    return resolution


def get_timezone(of_user=False) -> pytz.BaseTzInfo:
    """Return the FlexMeasures timezone, or if desired try to return the timezone of the current user."""
    default_timezone = pytz.timezone(
        current_app.config.get("FLEXMEASURES_TIMEZONE", "")
    )
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
    now = server_now()
    return now.replace(minute=now.minute - (now.minute % 15), second=0, microsecond=0)


def get_most_recent_hour() -> datetime:
    now = server_now()
    return now.replace(minute=now.minute - (now.minute % 60), second=0, microsecond=0)


def get_most_recent_clocktime_window(
    window_size_in_minutes: int, now: Optional[datetime] = None
) -> Tuple[datetime, datetime]:
    """
    Calculate a recent time window, returning a start and end minute so that
    a full hour can be filled with such windows, e.g.:

    Calling this function at 15:01:xx with window size 5 -> (14:55:00, 15:00:00)
    Calling this function at 03:36:xx with window size 15 -> (03:15:00, 03:30:00)

    window_size_in_minutes is assumed to > 0 and < = 60, and a divisor of 60 (1, 2, ..., 30, 60).

    If now is not given, the current server time is used.
    if now / the current time lies within a boundary minute (e.g. 15 when window_size_in_minutes=5),
    then the window is not deemed over and the previous one is returned (in this case, [5, 10])

    Returns two datetime objects. They'll be in the timezone (if given) of the now parameter,
    or in the server timezone (see FLEXMEASURES_TIMEZONE setting).
    """
    assert window_size_in_minutes > 0
    assert 60 % window_size_in_minutes == 0
    if now is None:
        now = server_now()
    last_full_minute = now.replace(second=0, microsecond=0) - timedelta(minutes=1)
    last_round_minute = last_full_minute.minute - (
        last_full_minute.minute % window_size_in_minutes
    )
    begin_time = last_full_minute.replace(minute=last_round_minute) - timedelta(
        minutes=window_size_in_minutes
    )
    end_time = begin_time + timedelta(minutes=window_size_in_minutes)
    return begin_time, end_time


def get_default_start_time() -> datetime:
    return get_most_recent_quarter() - timedelta(days=1)


def get_default_end_time() -> datetime:
    return get_most_recent_quarter() + timedelta(days=1)


def get_first_day_of_next_month() -> datetime:
    return (datetime.now().replace(day=1) + timedelta(days=32)).replace(day=1)


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
    if resolution_str in ("5T", "10T"):
        horizons = ["1h", "6h", "24h"]
    elif resolution_str in ("15T", "1h", "H"):
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


def duration_isoformat(duration: timedelta):
    """Adapted version of isodate.duration_isoformat for formatting a datetime.timedelta.

    The difference is that absolute days are not formatted as nominal days.
    Workaround for https://github.com/gweis/isodate/issues/74.
    """
    ret = []
    usecs = abs(
        (duration.days * 24 * 60 * 60 + duration.seconds) * 1000000
        + duration.microseconds
    )
    seconds, usecs = divmod(usecs, 1000000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours or minutes or seconds or usecs:
        ret.append("T")
        if hours:
            ret.append("%sH" % hours)
        if minutes:
            ret.append("%sM" % minutes)
        if seconds or usecs:
            if usecs:
                ret.append(("%d.%06d" % (seconds, usecs)).rstrip("0"))
            else:
                ret.append("%d" % seconds)
            ret.append("S")
    # at least one component has to be there.
    repl = ret and "".join(ret) or "T0H"
    return re.sub("%P", repl, "P%P")
