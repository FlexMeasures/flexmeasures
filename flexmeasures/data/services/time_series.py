from __future__ import annotations

from typing import Any
from datetime import timedelta

from flask import current_app
import numpy as np
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


CANONICAL_INDEX_ORDER = [
    "event_start",
    "belief_time",
    "source",
    "cumulative_probability",
]


def drop_unchanged_beliefs(bdf: tb.BeliefsDataFrame) -> tb.BeliefsDataFrame:
    """Drop beliefs that say the same as the belief right before them.

    A belief is unchanged if the belief right before it, about the same event and from the same source,
    gives the same value for each cumulative probability.
    "Right before" is in belief-time order, among the beliefs already stored and the ones being saved together,
    so a value that changes and changes back is kept, also when the whole change arrives in one save.
    Of a run of equal beliefs, the earliest is kept, so a value is known from the moment it was first believed.

    Quite useful function to prevent cluttering up your database with beliefs that remain unchanged over time,
    and to prevent duplicate key violations when re-running forecasters or reporters with identical data.
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
        return pd.concat([ex_ante_bdf, ex_post_bdf])

    # Look up the stored beliefs of the same kind and from the same sources, so that each new belief can be compared with the one right before it.
    source_ids = [source.id for source in bdf.lineage.sources if source.id is not None]
    if not source_ids:
        # Sources without an ID were not flushed yet, so nothing stored can be theirs.
        return _drop_unchanged_beliefs_compared_to_db(bdf, bdf_db=None)
    if bdf.belief_horizons[0] > timedelta(0):
        # Look up only ex-ante beliefs (horizon > 0)
        kwargs = dict(horizons_at_least=timedelta(0))
    else:
        # Look up only ex-post beliefs (horizon <= 0)
        kwargs = dict(horizons_at_most=timedelta(0))
    bdf_db = bdf.sensor.search_beliefs(
        event_starts_after=bdf.event_starts.min(),
        event_ends_before=bdf.event_ends.max(),
        source=source_ids,
        most_recent_beliefs_only=False,  # all beliefs
        **kwargs,
    )
    return _drop_unchanged_beliefs_compared_to_db(bdf, bdf_db=bdf_db)


def _drop_unchanged_beliefs_compared_to_db(
    bdf: tb.BeliefsDataFrame,
    bdf_db: tb.BeliefsDataFrame | None,
) -> tb.BeliefsDataFrame:
    """Drop the beliefs in bdf that say the same as the belief right before them, among the beliefs in bdf and bdf_db together.

    Assumes either all ex-ante beliefs or all ex-post beliefs.
    Beliefs are compared whole: a probabilistic belief is unchanged only if every one of its cumulative probabilities has the same value,
    and if any of them changed, the whole belief is kept, not just the parts that changed.

    Three cases are handled:

    1. **Unchanged belief** — the belief right before it says the same, whether that belief is stored or arrives in the same save:
       the candidate is dropped to avoid cluttering the database with redundant history.
    2. **Exact duplicate** — a belief with the exact same belief time is already stored with the same value:
       a stored belief counts as coming right before a new one at the same belief time,
       so the candidate is dropped, which prevents duplicate key violations when re-running forecasters or reporters with identical data.
       A different value at the same belief time is kept, leaving it to the caller to replace or refuse the stored one.
    3. **Repeated row** — the same row occurs more than once in bdf, as when overlapping chunks are concatenated:
       it is kept once, since its copies would otherwise fail the save on the unique constraint.

    Sources are compared by ID rather than by object identity:
    the candidates may have been deserialized from an RQ job queue (pickled in a different process),
    so their DataSource objects are detached and are not identical to the freshly loaded ones in bdf_db, even when they represent the same row.

    It is preferable to call the public function drop_unchanged_beliefs instead.
    """
    if bdf.empty:
        return bdf
    bdf = bdf.convert_index_from_belief_horizon_to_time().reorder_levels(
        CANONICAL_INDEX_ORDER
    )
    # One numbering of the rows, and of their sources, serves both the comparison and the selection at the end.
    rows = _belief_keys_per_row(bdf)
    repeated = rows.duplicated().to_numpy()
    new = _beliefs_as_distributions(rows[~repeated])
    if bdf_db is not None and not bdf_db.empty:
        stored = _beliefs_as_distributions(
            _belief_keys_per_row(bdf_db.convert_index_from_belief_horizon_to_time())
        )
        # Only the events and sources being saved matter.
        stored = stored[
            stored["event_start"].isin(new["event_start"])
            & stored["source_id"].isin(new["source_id"])
        ]
    else:
        stored = new.iloc[0:0]

    # Line up all beliefs about each event from each source in belief-time order,
    # with a stored belief coming right before a new one at the same belief time.
    sequence = pd.concat(
        [stored.assign(is_new=False), new.assign(is_new=True)], ignore_index=True
    ).sort_values(["event_start", "source_id", "belief_time", "is_new"])
    previous = sequence.groupby(["event_start", "source_id"], sort=False)[
        "distribution"
    ].shift()
    unchanged = sequence["distribution"] == previous
    kept = sequence[sequence["is_new"] & ~unchanged]

    # Keep every row of each kept belief, once, selecting rows of the original frame so that its metadata stays intact.
    belief_keys = ["event_start", "source_id", "belief_time"]
    is_kept = pd.MultiIndex.from_frame(rows[belief_keys]).isin(
        pd.MultiIndex.from_frame(kept[belief_keys])
    )
    return bdf[is_kept & ~repeated]


def _source_keys(index: pd.MultiIndex) -> np.ndarray:
    """The ID of each row's source, or a negative number unique to each source that has no ID yet.

    Each distinct source is looked up once, and its key is spread over its rows through the index's codes.
    A source that was not flushed yet has no ID, so it matches no stored belief,
    and two such sources in one save must not be taken for one and the same source.
    """
    level = index.names.index("source")
    keys = []
    unsaved = 0
    for source in index.levels[level]:
        if source.id is None:
            unsaved += 1
            keys.append(-unsaved)
        else:
            keys.append(source.id)
    return np.asarray(keys, dtype="int64")[index.codes[level]]


def _belief_keys_per_row(bdf: tb.BeliefsDataFrame) -> pd.DataFrame:
    """The event start, source key, belief time, cumulative probability and value of each row, in the frame's row order.

    Expects a frame indexed by belief time.
    """
    return pd.DataFrame(
        {
            "event_start": bdf.index.get_level_values("event_start"),
            "source_id": _source_keys(bdf.index),
            "belief_time": bdf.index.get_level_values("belief_time"),
            "cumulative_probability": bdf.index.get_level_values(
                "cumulative_probability"
            ),
            "event_value": bdf["event_value"].to_numpy(),
        }
    )


def _beliefs_as_distributions(rows: pd.DataFrame) -> pd.DataFrame:
    """One row per belief, holding its whole distribution as a tuple of (cumulative probability, value) pairs.

    Takes the rows of a frame as `_belief_keys_per_row` describes them.
    """
    rows = rows.sort_values(
        ["event_start", "source_id", "belief_time", "cumulative_probability"]
    )
    belief_keys = ["event_start", "source_id", "belief_time"]
    # A missing value repeats a missing value, as it always did, so NaN is replaced by None, which equals itself.
    values = rows["event_value"].astype(object).where(rows["event_value"].notna(), None)
    if not rows.duplicated(belief_keys).any():
        # Deterministic beliefs (one row each) are by far the most common, and need no grouping.
        # Each is still wrapped as a tuple of pairs, so that it compares equal to the same belief from the grouped path below.
        rows["distribution"] = [
            ((probability, value),)
            for probability, value in zip(rows["cumulative_probability"], values)
        ]
        return rows[belief_keys + ["distribution"]].reset_index(drop=True)
    rows["pair"] = list(zip(rows["cumulative_probability"], values))
    return (
        rows.groupby(belief_keys, sort=False)["pair"]
        .agg(tuple)
        .rename("distribution")
        .reset_index()
    )
