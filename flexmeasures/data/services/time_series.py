from __future__ import annotations

from typing import Any
from datetime import timedelta

from flask import current_app
import pandas as pd
import timely_beliefs as tb

from flexmeasures.data.queries.utils import simplify_index


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
    """Drop beliefs that are already stored in the database with an earlier or equal belief time.

    Also drop beliefs that are already in the data with an earlier belief time.

    Quite useful function to prevent cluttering up your database with beliefs that remain
    unchanged over time, and to prevent duplicate key violations when re-running forecasters
    or reporters with identical data.
    """
    if bdf.empty:
        return bdf
    bdf = bdf.convert_index_from_belief_horizon_to_time()
    # Save the oldest ex-post beliefs explicitly, even if they do not deviate from the most recent ex-ante beliefs
    ex_ante_bdf = bdf[bdf.belief_horizons > timedelta(0)]
    ex_post_bdf = bdf[bdf.belief_horizons <= timedelta(0)]
    canonical_order = ["event_start", "belief_time", "source", "cumulative_probability"]
    if not ex_ante_bdf.empty and not ex_post_bdf.empty:
        # We treat each part separately to avoid that ex-post knowledge would be lost
        ex_ante_bdf = drop_unchanged_beliefs(ex_ante_bdf).reorder_levels(
            canonical_order
        )
        ex_post_bdf = drop_unchanged_beliefs(ex_post_bdf).reorder_levels(
            canonical_order
        )
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
    if bdf.belief_horizons[0] > timedelta(0):
        # Look up only ex-ante beliefs (horizon > 0)
        kwargs = dict(horizons_at_least=timedelta(0))
    else:
        # Look up only ex-post beliefs (horizon <= 0)
        kwargs = dict(horizons_at_most=timedelta(0))
    bdf_db = bdf.sensor.search_beliefs(
        event_starts_after=bdf.event_starts[0],
        event_ends_before=bdf.event_ends[-1],
        most_recent_beliefs_only=False,  # all beliefs
        **kwargs,
    )
    if bdf_db.empty:
        return bdf
    ordered_bdf = _drop_unchanged_beliefs_compared_to_db(bdf, bdf_db=bdf_db)
    # Keep the canonical level order, also when the result is empty
    if ordered_bdf.index.names != canonical_order:
        ordered_bdf.index.names = canonical_order
    return ordered_bdf


def _utc_ns(values: pd.Series) -> pd.Series:
    """Express datetimes as UTC with nanosecond resolution, so that merge keys have identical dtypes."""
    return pd.to_datetime(values, utc=True).astype("datetime64[ns, UTC]")


def _drop_unchanged_beliefs_compared_to_db(
    bdf: tb.BeliefsDataFrame,
    bdf_db: tb.BeliefsDataFrame,
) -> tb.BeliefsDataFrame:
    """Drop beliefs that are already stored in the database with an earlier or equal belief time.

    Assumes all beliefs in ``bdf`` are either all ex-ante or all ex-post.
    A candidate belief is the set of rows (one per cumulative probability) that share an event start, belief time and source.
    It is compared with the stored belief of the same source and event start that has the latest belief time up to and including the candidate's.
    The candidate is dropped if all its (cumulative probability, event value) pairs occur in that stored belief,
    which covers both unchanged beliefs and exact duplicates (preventing duplicate key violations).
    Otherwise, the candidate is kept whole, including the pairs that did not change.
    A candidate without such a stored belief is kept.

    The whole frame is compared at once, which keeps this fast for many beliefs.
    It is preferable to call the public function drop_unchanged_beliefs instead.
    """
    canonical_order = ["event_start", "belief_time", "source", "cumulative_probability"]
    ordered = bdf.reorder_levels(canonical_order)
    cand = ordered.reset_index()
    stored = bdf_db.reset_index()

    # Compare sources by ID rather than object identity: the candidate bdf may have been
    # deserialized from an RQ job queue (pickled in a different process), so its
    # DataSource objects are detached and won't be identical to the freshly-loaded
    # ones in bdf_db even when they represent the same DB row.
    # A source without ID (not yet flushed) becomes NaN, which matches no stored belief.
    def source_ids(sources: pd.Series) -> pd.Series:
        ids = {s: s.id for s in sources.unique()}
        return pd.to_numeric(sources.map(ids), errors="coerce").astype("float64")

    cand_keys = pd.DataFrame(
        {
            "event_start": _utc_ns(cand["event_start"]),
            "source_id": source_ids(cand["source"]),
            "belief_time": _utc_ns(cand["belief_time"]),
            "cumulative_probability": cand["cumulative_probability"],
            "event_value": cand["event_value"],
            "_pos": range(len(cand)),
            "_candidate": cand.groupby(
                ["event_start", "belief_time", "source"], sort=False
            ).ngroup(),
        }
    )
    stored_keys = pd.DataFrame(
        {
            "event_start": _utc_ns(stored["event_start"]),
            "source_id": source_ids(stored["source"]),
            "stored_belief_time": _utc_ns(stored["belief_time"]),
            "cumulative_probability": stored["cumulative_probability"],
            "event_value": stored["event_value"],
        }
    )

    # Find the latest stored belief time not later than the candidate's, per event start and source
    by = ["event_start", "source_id"]
    stored_belief_times = (
        stored_keys[by + ["stored_belief_time"]]
        .drop_duplicates()
        .sort_values("stored_belief_time", kind="stable")
    )
    cand_keys = pd.merge_asof(
        cand_keys.sort_values("belief_time", kind="stable"),
        stored_belief_times,
        left_on="belief_time",
        right_on="stored_belief_time",
        by=by,
        direction="backward",
    )

    # A row is unchanged if that stored belief holds the same cumulative probability and event value
    compare = by + ["cumulative_probability", "event_value", "stored_belief_time"]
    cand_keys = cand_keys.merge(
        stored_keys[compare].drop_duplicates().assign(_unchanged=True),
        on=compare,
        how="left",
    )
    cand_keys["_unchanged"] = cand_keys["_unchanged"].notna()

    # Keep a candidate belief if it has no earlier stored belief, or if any of its rows changed
    all_unchanged = cand_keys.groupby("_candidate")["_unchanged"].transform("all")
    keep = cand_keys["stored_belief_time"].isna() | ~all_unchanged
    return ordered.iloc[cand_keys.loc[keep, "_pos"].to_numpy()].sort_index()
