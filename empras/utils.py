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
    df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, resolution: timedelta
) -> pd.DataFrame:

    # Slice data
    df = df[(df.index >= start) & (df.index < end)]

    # Ensure data reflects whole time range
    df = ensure_time_range(df, start, end, resolution)
    return df


def ensure_time_range(
    df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, resolution: timedelta
) -> pd.DataFrame:
    """Ensure data reflects whole time range, adding None rows at edges if needed."""
    end_index = end - resolution  # index of the desired last row in the DataFrame
    if start not in df.index:
        # add 1 row at start
        df = pd.concat(
            [
                pd.DataFrame(
                    None,
                    index=pd.date_range(start, start, name=df.index.name),
                    columns=df.columns,
                ),
                df,
            ]
        )
    if end_index not in df.index:
        # add 1 row at end
        df = pd.concat(
            [
                df,
                pd.DataFrame(
                    None,
                    index=pd.date_range(end_index, end_index, name=df.index.name),
                    columns=df.columns,
                ),
            ]
        )
    return df
