from __future__ import annotations

from typing import Any
from datetime import timedelta

import inflect
from flask import current_app
import pandas as pd
import timely_beliefs as tb

from flexmeasures.data.queries.utils import simplify_index


p = inflect.engine()


def aggregate_values(bdf_dict: dict[Any, tb.BeliefsDataFrame]) -> tb.BeliefsDataFrame:
    # todo: test this function rigorously, e.g. with empty bdfs in bdf_dict
    # todo: consider 1 bdf with beliefs from source A, plus 1 bdf with beliefs from source B -> 1 bdf with sources A+B
    # todo: consider 1 bdf with beliefs from sources A and B, plus 1 bdf with beliefs from source C. -> 1 bdf with sources A+B and A+C
    # todo: consider 1 bdf with beliefs from sources A and B, plus 1 bdf with beliefs from source C and D. -> 1 bdf with sources A+B, A+C, B+C and B+D
    # Relevant issue: https://github.com/SeitaBV/timely-beliefs/issues/33

    # Nothing to aggregate
    if len(bdf_dict) == 1:
        return list(bdf_dict.values())[0]

    unique_source_ids: list[int] = []
    for bdf in bdf_dict.values():
        unique_source_ids.extend(bdf.lineage.sources)
        if not bdf.lineage.unique_beliefs_per_event_per_source:
            current_app.logger.warning(
                "Not implemented: only aggregation of deterministic uni-source beliefs (1 per event) is properly supported"
            )
        if bdf.lineage.number_of_sources > 1:
            current_app.logger.warning(
                "Not implemented: aggregating multi-source beliefs about the same sensor."
            )
    if len(set(unique_source_ids)) > 1:
        current_app.logger.warning(
            f"Not implemented: aggregating multi-source beliefs. Source {unique_source_ids[1:]} will be treated as if source {unique_source_ids[0]}"
        )

    data_as_bdf = tb.BeliefsDataFrame()
    for k, v in bdf_dict.items():
        if data_as_bdf.empty:
            data_as_bdf = v.copy()
        elif not v.empty:
            data_as_bdf["event_value"] = data_as_bdf["event_value"].add(
                simplify_index(v.copy())["event_value"],
                fill_value=0,
                level="event_start",
            )  # we only look at the event_start index level and sum up duplicates that level
    return data_as_bdf


def drop_unchanged_beliefs(bdf: tb.BeliefsDataFrame) -> tb.BeliefsDataFrame:
    """Drop beliefs that are already stored in the database with an earlier belief time.

    Also drop beliefs that are already in the data with an earlier belief time.

    Quite useful function to prevent cluttering up your database with beliefs that remain unchanged over time.
    """
    if bdf.empty:
        return bdf

    # Save the oldest ex-post beliefs explicitly, even if they do not deviate from the most recent ex-ante beliefs
    ex_ante_bdf = bdf[bdf.belief_horizons > timedelta(0)]
    ex_post_bdf = bdf[bdf.belief_horizons <= timedelta(0)]
    if not ex_ante_bdf.empty and not ex_post_bdf.empty:
        # We treat each part separately to avoid that ex-post knowledge would be lost
        ex_ante_bdf = drop_unchanged_beliefs(ex_ante_bdf)
        ex_post_bdf = drop_unchanged_beliefs(ex_post_bdf)
        bdf = pd.concat([ex_ante_bdf, ex_post_bdf])
        return bdf

    # Remove unchanged beliefs from within the new data itself
    index_names = bdf.index.names
    bdf = (
        bdf.sort_index()
        .reset_index()
        .drop_duplicates(
            ["event_start", "source", "cumulative_probability", "event_value"],
            keep="first",
        )
        .set_index(index_names)
    )

    # Remove unchanged beliefs with respect to what is already stored in the database
    return (
        bdf.convert_index_from_belief_horizon_to_time()
        .groupby(level=["belief_time", "source"], group_keys=False, as_index=False)
        .apply(_drop_unchanged_beliefs_compared_to_db)
    )


def _drop_unchanged_beliefs_compared_to_db(
    bdf: tb.BeliefsDataFrame,
) -> tb.BeliefsDataFrame:
    """Drop beliefs that are already stored in the database with an earlier belief time.

    Assumes a BeliefsDataFrame with a unique belief time and unique source,
    and either all ex-ante beliefs or all ex-post beliefs.

    It is preferable to call the public function drop_unchanged_beliefs instead.
    """
    if bdf.belief_horizons[0] > timedelta(0):
        # Look up only ex-ante beliefs (horizon > 0)
        kwargs = dict(horizons_at_least=timedelta(0))
    else:
        # Look up only ex-post beliefs (horizon <= 0)
        kwargs = dict(horizons_at_most=timedelta(0))
    previous_most_recent_beliefs_in_db = bdf.sensor.search_beliefs(
        event_starts_after=bdf.event_starts[0],
        event_ends_before=bdf.event_ends[-1],
        beliefs_before=bdf.lineage.belief_times[0],  # unique belief time
        source=bdf.lineage.sources[0],  # unique source
        most_recent_beliefs_only=True,
        **kwargs,
    )

    compare_fields = ["event_start", "source", "cumulative_probability", "event_value"]
    a = bdf.reset_index().set_index(compare_fields)
    b = previous_most_recent_beliefs_in_db.reset_index().set_index(compare_fields)
    bdf = a.drop(
        b.index,
        errors="ignore",
        axis=0,
    )

    # Keep whole probabilistic beliefs, not just the parts that changed
    c = bdf.reset_index().set_index(["event_start", "source"])
    d = a.reset_index().set_index(["event_start", "source"])
    bdf = d[d.index.isin(c.index)]

    bdf = bdf.reset_index().set_index(
        ["event_start", "belief_time", "source", "cumulative_probability"]
    )
    return bdf
