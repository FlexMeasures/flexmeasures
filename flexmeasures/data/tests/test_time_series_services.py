import pandas as pd
from timely_beliefs import BeliefsDataFrame, utils as tb_utils
import pytest
from sqlalchemy.exc import IntegrityError

from flexmeasures.data.utils import save_to_db
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.time_series import TimedBelief
from flexmeasures.data.services.time_series import (
    _drop_unchanged_beliefs_compared_to_db,
    drop_unchanged_beliefs,
)
from flexmeasures.tests.utils import get_test_sensor


def test_drop_unchanged_beliefs(setup_beliefs, db):
    """Trying to save beliefs that are already in the database shouldn't raise an error.

    Even after updating the belief time, we expect to persist only the older belief time.
    """

    # Set a reference for the number of beliefs stored and their belief times
    sensor = get_test_sensor(db)
    bdf = sensor.search_beliefs(most_recent_beliefs_only=False)
    num_beliefs_before = len(bdf)
    belief_times_before = bdf.belief_times

    # See what happens when storing all existing beliefs verbatim
    save_to_db(bdf)

    # Verify that no new beliefs were saved
    bdf = sensor.search_beliefs(most_recent_beliefs_only=False)
    assert len(bdf) == num_beliefs_before

    # See what happens when storing all beliefs with their belief time updated
    bdf = tb_utils.replace_multi_index_level(
        bdf, "belief_time", bdf.belief_times + pd.Timedelta("1h")
    )
    save_to_db(bdf)

    # Verify that no new beliefs were saved
    bdf = sensor.search_beliefs(most_recent_beliefs_only=False)
    assert len(bdf) == num_beliefs_before
    assert list(bdf.belief_times) == list(belief_times_before)


def test_do_not_drop_beliefs_copied_by_another_source(setup_beliefs, db):
    """Trying to copy beliefs from one source to another should double the number of beliefs."""

    # Set a reference for the number of beliefs stored
    sensor = get_test_sensor(db)
    bdf = sensor.search_beliefs(most_recent_beliefs_only=False)
    num_beliefs_before = len(bdf)

    # See what happens when storing all belief with their source updated
    new_source = DataSource(name="Not Seita", type="demo script")
    bdf = tb_utils.replace_multi_index_level(
        bdf, "source", pd.Index([new_source] * num_beliefs_before)
    )
    save_to_db(bdf)

    # Verify that all the new beliefs were added
    bdf = sensor.search_beliefs(most_recent_beliefs_only=False)
    num_beliefs_after = len(bdf)
    assert num_beliefs_after == 2 * num_beliefs_before


def test_do_not_drop_changed_probabilistic_belief(setup_beliefs, db):
    """Trying to save a changed probabilistic belief should result in saving the whole belief.

    For example, given a belief that defines both cp=0.2 and cp=0.5,
    if that belief becomes more certain (e.g. cp=0.3 and cp=0.5),
    we expect to see the full new belief stored, rather than just the cp=0.3 value.
    """

    # Set a reference for the number of beliefs stored
    sensor = get_test_sensor(db)
    bdf = sensor.search_beliefs(source="ENTSO-E", most_recent_beliefs_only=False)
    assert not bdf.empty
    assert (
        bdf.lineage.probabilistic_depth > 1
    ), "Expected probabilistic data for this test"
    num_beliefs_before = len(bdf)

    # See what happens when storing a belief with more certainty one hour later
    old_belief = bdf.loc[
        (
            bdf.index.get_level_values("event_start")
            == pd.Timestamp("2021-03-28 16:00:00+00:00")
        )
        & (
            bdf.index.get_level_values("belief_time")
            == pd.Timestamp("2021-03-27 9:00:00+00:00")
        )
    ]
    new_belief = tb_utils.replace_multi_index_level(
        old_belief, "cumulative_probability", pd.Index([0.3, 0.5])
    )
    new_belief = tb_utils.replace_multi_index_level(
        new_belief, "belief_time", new_belief.belief_times + pd.Timedelta("1h")
    )
    save_to_db(new_belief)

    # Verify that the whole probabilistic belief was added
    bdf = sensor.search_beliefs(source="ENTSO-E", most_recent_beliefs_only=False)
    num_beliefs_after = len(bdf)
    assert num_beliefs_after == num_beliefs_before + len(new_belief)


@pytest.mark.parametrize(
    "sort_descending",
    [
        pytest.param(False, id="ascending_belief_times"),
        pytest.param(True, id="descending_belief_times"),
    ],
)
def test_drop_unchanged_compares_against_latest_prior_belief(
    setup_beliefs, db, sort_descending
):
    """Candidate equal to an older belief should still compare to latest prior,
    regardless of whether the existing DB beliefs are sorted ascending or descending.

    Scenario:
      belief_time_1 (oldest)  → value 2.0
      belief_time_2 (latest prior) → value 1.0
      belief_time_3 (candidate)    → value 2.0  ← must NOT be dropped
    """

    sensor = get_test_sensor(db)
    assert sensor is not None, "Expected a test sensor to exist in the test database"
    source = DataSource(name="Drop unchanged repro source", type="demo script")
    db.session.add(source)
    db.session.commit()

    event_start = pd.Timestamp("2021-03-28 16:00:00+00:00")
    belief_time_1 = pd.Timestamp("2021-03-27 08:00:00+00:00")  # older value: 2
    belief_time_2 = pd.Timestamp("2021-03-27 09:00:00+00:00")  # latest prior value: 1
    belief_time_3 = pd.Timestamp("2021-03-27 10:00:00+00:00")  # candidate value: 2

    bdf_db = BeliefsDataFrame(
        [
            TimedBelief(
                sensor=sensor,
                source=source,
                event_start=event_start,
                belief_time=belief_time_1,
                event_value=2.0,
            ),
            TimedBelief(
                sensor=sensor,
                source=source,
                event_start=event_start,
                belief_time=belief_time_2,
                event_value=1.0,
            ),
        ]
    )

    if sort_descending:
        bdf_db = bdf_db.sort_index(ascending=False)
        assert list(bdf_db.belief_times) == [
            belief_time_2,
            belief_time_1,
        ], "Pre-condition failed: expected bdf_db to be sorted with newest belief first"

    candidate = BeliefsDataFrame(
        [
            TimedBelief(
                sensor=sensor,
                source=source,
                event_start=event_start,
                belief_time=belief_time_3,
                event_value=2.0,
            )
        ]
    )

    filtered = _drop_unchanged_beliefs_compared_to_db(candidate, bdf_db=bdf_db)
    assert len(filtered) == 1, (
        "Candidate belief (value=2.0) should not be dropped: it differs from the latest "
        "prior belief (value=1.0 at belief_time_2), even though it equals an older belief "
        "(value=2.0 at belief_time_1)"
    )


def test_drop_unchanged_belief_with_multi_event_start_db(setup_beliefs, db):
    """An unchanged belief for event_start T1 must be dropped even when bdf_db also contains
    a belief for a different event_start T2 whose belief_time is more recent.

    Without the ``& (bdf_db.event_starts == event_start)`` filter in
    ``_drop_unchanged_beliefs_compared_to_db``, ``most_recent_bt`` could be taken from T2's
    belief row, causing the T1 candidate to be compared against T2's value rather than T1's,
    and the unchanged candidate would NOT be dropped.
    """
    sensor = get_test_sensor(db)
    source = DataSource(name="Multi-event-start repro source", type="demo script")
    db.session.add(source)
    db.session.commit()

    event_start_1 = pd.Timestamp("2021-03-28 16:00:00+00:00")
    event_start_2 = pd.Timestamp("2021-03-28 17:00:00+00:00")
    belief_time_t1 = pd.Timestamp("2021-03-27 08:00:00+00:00")  # older BT for T1
    belief_time_t2 = pd.Timestamp("2021-03-27 09:00:00+00:00")  # newer BT for T2
    belief_time_candidate = pd.Timestamp("2021-03-27 10:00:00+00:00")  # candidate BT

    # bdf_db has beliefs for both event_starts; T2 has the more recent belief_time
    bdf_db = BeliefsDataFrame(
        [
            TimedBelief(
                sensor=sensor,
                source=source,
                event_start=event_start_1,
                belief_time=belief_time_t1,
                event_value=42.0,
            ),
            TimedBelief(
                sensor=sensor,
                source=source,
                event_start=event_start_2,
                belief_time=belief_time_t2,
                event_value=99.0,
            ),
        ]
    )

    # Candidate for T1 with the same value as the existing T1 belief → should be dropped
    candidate = BeliefsDataFrame(
        [
            TimedBelief(
                sensor=sensor,
                source=source,
                event_start=event_start_1,
                belief_time=belief_time_candidate,
                event_value=42.0,
            )
        ]
    )

    filtered = _drop_unchanged_beliefs_compared_to_db(candidate, bdf_db=bdf_db)
    assert len(filtered) == 0, (
        "Unchanged candidate (value=42.0 for event_start_1) should be dropped: "
        "the latest prior belief for event_start_1 already has the same value. "
        "Without the event_start filter the code wrongly picks T2's newer belief_time "
        "as most_recent_bt and compares against T2's value instead of T1's."
    )


def test_drop_unchanged_beliefs_preserves_index_names_with_mixed_groups(
    setup_beliefs, db
):
    """drop_unchanged_beliefs must preserve all MultiIndex level names when some event_starts
    are already in the DB (those groups become empty after filtering) while others are new.

    Regression test for a pandas 2.x bug where groupby(...).apply() drops level names
    for non-grouped levels when mixed empty/non-empty groups are concatenated and the
    index level order of the applied function's output differs from the groupby input.

    Without the fix (reorder_levels to canonical order before groupby + restoring names
    after apply), the returned DataFrame has None for the 'source' and
    'cumulative_probability' level names, causing the subsequent reorder_levels() call
    in drop_unchanged_beliefs to raise KeyError: 'Level source not found'.
    """
    sensor = get_test_sensor(db)
    source = DataSource(name="Mixed groups repro source", type="demo script")
    db.session.add(source)
    db.session.commit()

    belief_time = pd.Timestamp("2021-03-27 08:00:00+00:00")
    # T1: already stored in DB with the same value → will become an empty group in apply()
    event_start_existing = pd.Timestamp("2021-03-28 16:00:00+00:00")
    # T2: not yet in DB → will become a non-empty group in apply()
    event_start_new = pd.Timestamp("2021-03-28 17:00:00+00:00")
    existing_value = 42.0
    new_value = 99.0

    # Pre-populate the DB with a belief for T1
    bdf_seed = BeliefsDataFrame(
        [
            TimedBelief(
                sensor=sensor,
                source=source,
                event_start=event_start_existing,
                belief_time=belief_time,
                event_value=existing_value,
            )
        ]
    )
    save_to_db(bdf_seed)

    # Candidate BDF spans both T1 (unchanged, same value) and T2 (new)
    bdf_candidate = BeliefsDataFrame(
        [
            TimedBelief(
                sensor=sensor,
                source=source,
                event_start=event_start_existing,
                belief_time=belief_time,
                event_value=existing_value,  # identical → should be dropped
            ),
            TimedBelief(
                sensor=sensor,
                source=source,
                event_start=event_start_new,
                belief_time=belief_time,
                event_value=new_value,  # new → should be kept
            ),
        ]
    )
    # Simulate the non-canonical index level order observed in production (e.g. after
    # passing through pandas reset_index/set_index round-trips in reporters).  The bug
    # only manifests when cumulative_probability appears before source in the index.
    bdf_candidate = bdf_candidate.reorder_levels(
        ["event_start", "belief_time", "cumulative_probability", "source"]
    )

    # This call must not raise KeyError: 'Level source not found'
    result = drop_unchanged_beliefs(bdf_candidate)

    # The result must have all four named index levels
    assert result.index.names == [
        "event_start",
        "belief_time",
        "source",
        "cumulative_probability",
    ], f"Index level names were corrupted: {result.index.names}"

    # The unchanged belief for T1 must have been dropped; the new T2 belief must remain
    assert (
        len(result) == 1
    ), f"Expected only the new belief to survive, got {len(result)} rows"
    assert result.event_starts[0] == event_start_new


def test_save_exact_duplicate_deterministic_belief(setup_beliefs, db):
    """Saving an exact duplicate deterministic belief should succeed without errors."""

    # Get beliefs from the database
    sensor = get_test_sensor(db)
    bdf = sensor.search_beliefs(
        source="ENTSO-E",
        most_recent_beliefs_only=False,
    )
    assert not bdf.empty

    # Get the first belief to test with (it should be deterministic)
    test_bdf = bdf.iloc[:1].copy()

    num_beliefs_before = len(sensor.search_beliefs(most_recent_beliefs_only=False))

    # Try to save the exact same belief again (with save_changed_beliefs_only=True, duplicates are dropped)
    save_to_db(test_bdf, save_changed_beliefs_only=True)

    # Verify that the save succeeded and the belief count remained the same
    num_beliefs_after = len(sensor.search_beliefs(most_recent_beliefs_only=False))
    # The count should remain the same (unchanged beliefs are dropped by save_to_db)
    assert num_beliefs_after == num_beliefs_before


def test_save_duplicate_probabilistic_belief_with_different_cp(
    db, setup_probabilistic_beliefs
):
    """Saving a duplicate probabilistic belief (same event_start/source/belief_time but different cp) should succeed.

    This tests that multiple cumulative probabilities for the same event can coexist.
    """

    sensor = setup_probabilistic_beliefs["epex_da"]["sensor"]
    bdf = sensor.search_beliefs(source="ENTSO-E", most_recent_beliefs_only=False)
    assert not bdf.empty
    assert (
        bdf.lineage.probabilistic_depth > 1
    ), "Expected probabilistic data for this test"

    # Create a new belief with different cp values but same event_start/source/belief_time
    # Get the first probabilistic belief and add a new cp value
    first_belief = bdf.iloc[:1].copy()

    # Create a new row with a different cp value (e.g., 0.7) by resetting and recreating the index
    new_cp_belief = first_belief.reset_index()
    new_cp_belief["cumulative_probability"] = 0.7
    new_cp_belief = new_cp_belief.set_index(
        ["event_start", "belief_time", "source", "cumulative_probability"]
    )

    # Try to save this new probabilistic belief variant
    save_to_db(new_cp_belief, save_changed_beliefs_only=False)

    # Verify that the save succeeded
    bdf_after = sensor.search_beliefs(source="ENTSO-E", most_recent_beliefs_only=False)
    # The belief should have been added
    assert len(bdf_after) >= len(bdf)


def test_save_deterministic_belief_with_different_event_value_raises_error(
    setup_beliefs, db
):
    """Saving a deterministic belief with same event_start/source/belief_time but different event_value should raise an error.

    This tests that replacing beliefs (changing the history) is not allowed.
    """

    # Get a deterministic belief from the database
    sensor = get_test_sensor(db)
    bdf = sensor.search_beliefs(
        source="ENTSO-E",
        most_recent_beliefs_only=False,
    )
    # Filter to only deterministic beliefs
    deterministic_bdf = bdf[
        ~bdf.index.get_level_values("cumulative_probability").isin([0.2, 0.5])
    ]
    assert not deterministic_bdf.empty

    # Modify the event value of the first belief
    modified_bdf = deterministic_bdf.iloc[:1].copy()
    modified_bdf.iloc[0, 0] = (
        modified_bdf.iloc[0, 0] + 999
    )  # Change the value significantly

    # Try to save this modified belief - it should raise an IntegrityError, because we're trying to replace an existing belief
    with pytest.raises(IntegrityError):
        save_to_db(modified_bdf, save_changed_beliefs_only=False)
        db.session.flush()  # Force the error to be raised

    # Rollback the session to clean up after the failed transaction
    db.session.rollback()


def test_save_probabilistic_belief_with_different_event_value_raises_error(
    db, setup_probabilistic_beliefs
):
    """Saving a probabilistic belief with same event_start/source/belief_time/cp but different event_value should raise an error.

    This tests that replacing beliefs (changing the history) is not allowed, even for probabilistic beliefs.
    """

    sensor = setup_probabilistic_beliefs["epex_da"]["sensor"]
    bdf = sensor.search_beliefs(most_recent_beliefs_only=False)
    assert not bdf.empty
    assert (
        bdf.lineage.probabilistic_depth > 1
    ), "Expected probabilistic data for this test"

    # Modify the event value of the first belief
    modified_bdf = bdf.iloc[:1].copy()
    modified_bdf.iloc[0, 0] = (
        modified_bdf.iloc[0, 0] + 999
    )  # Change the value significantly

    # Try to save this modified belief - it should raise an IntegrityError
    with pytest.raises(IntegrityError):
        save_to_db(modified_bdf, save_changed_beliefs_only=False)
        db.session.flush()  # Force the error to be raised

    # Rollback the session to clean up after the failed transaction
    db.session.rollback()


"""
The last tests intentionally trigger database errors and call db.session.rollback() to recover.
These rollbacks here corrupt the sensor / belief state that subsequent tests in this module may rely on.
The tests themselves seem to rely on earlier tests in this module.
Add new tests in this module above the tests that roll back the session.
If added below, they may pass in isolation, but fail if the whole module is ran.
"""
