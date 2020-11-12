from datetime import date, timedelta
from typing import Tuple

import pandas as pd
from flask import request


def determine_time_window_from_request(
    df: pd.DataFrame, default_timezone: str
) -> Tuple[pd.Timestamp, pd.Timestamp]:
    """Interpret requested time window.

    The default time window is 1 day long.
    We try to cater to an underspecified request if it just misses a start or end.
    Otherwise, we take today or the most recent day of data (if today is empty).
    """

    # Interpret request
    tz = request.args.get(
        "timezone", default_timezone
    )  # Set timezone for interpreting dates
    start = pd.Timestamp(request.args.get("startDate", None), tz=tz)
    end = pd.Timestamp(request.args.get("endDate", None), tz=tz)

    # Take 1 day if the time window is underspecified
    if not pd.isna(start) and pd.isna(end):
        end = start + pd.DateOffset(days=1)
    elif pd.isna(start) and not pd.isna(end):
        start = end - pd.DateOffset(days=1)
    elif pd.isna(start) and pd.isna(end):
        # Take current day if it has data
        start = pd.Timestamp(date.today(), tz=tz)
        end = start + pd.DateOffset(days=1)

        # Take the last day with data otherwise
        if df[(df.index >= start) & (df.index < end)].empty:
            start = df.index.tz_convert(tz).max().floor("1D")
            end = start + pd.DateOffset(days=1)

    return start, end


def slice_data(
    df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp
) -> pd.DataFrame:

    # Slice data
    df = df[(df.index >= start) & (df.index < end)]

    return df


def add_none_rows_to_help_charts(
    df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, resolution: timedelta
):
    """Ensure data reflects whole time range, adding None rows if needed."""

    index = pd.date_range(
        start, end, freq=resolution, closed="left", name=df.index.name
    ).difference(df.index)
    df_to_add = pd.DataFrame(None, index, columns=df.columns)
    df_to_add["dt_e"] = df_to_add.index + resolution

    return pd.concat([df, df_to_add]).sort_index()
