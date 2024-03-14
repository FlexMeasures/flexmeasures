from __future__ import annotations

from datetime import datetime
from itertools import chain
from textwrap import wrap

import pandas as pd


def stack_annotations(x: pd.DataFrame) -> pd.DataFrame:
    """Select earliest start, and include all annotations as a list.

    The list of strings results in a multi-line text encoding in the chart.
    """
    x = x.sort_values(["start", "belief_time"], ascending=True)
    x["content"].iloc[0] = list(chain(*(x["content"].tolist())))
    return x.head(1)


def prepare_annotations_for_chart(
    df: pd.DataFrame,
    event_starts_after: datetime | None = None,
    event_ends_before: datetime | None = None,
    max_line_length: int = 60,
) -> pd.DataFrame:
    """Prepare a DataFrame with annotations for use in a chart.

    - Clips annotations outside the requested time window.
    - Wraps on whitespace with a given max line length
    - Stacks annotations for the same event
    """

    # Clip annotations outside the requested time window
    if event_starts_after is not None:
        df.loc[df["start"] < event_starts_after, "start"] = event_starts_after
    if event_ends_before is not None:
        df.loc[df["end"] > event_ends_before, "end"] = event_ends_before

    # Wrap on whitespace with some max line length
    df["content"] = df["content"].apply(wrap, args=[max_line_length])

    # Stack annotations for the same event
    if not df.empty:
        df = df.groupby("end", group_keys=False).apply(stack_annotations)

    return df
