import pandas as pd
from timely_beliefs import utils as tb_utils
import pytest
from sqlalchemy.exc import IntegrityError

from flexmeasures.data.utils import save_to_db
from flexmeasures.data.models.data_sources import DataSource
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


def test_drop_unchanged_compares_against_latest_prior_belief(setup_beliefs, db):
    """Repro: candidate equal to an older belief should still compare to latest prior."""

    sensor = get_test_sensor(db)
    assert sensor is not None
    source = DataSource(name="Drop unchanged repro source", type="demo script")
    db.session.add(source)
    db.session.commit()

    event_start = pd.Timestamp("2021-03-28 16:00:00+00:00")
    belief_time_1 = pd.Timestamp("2021-03-27 08:00:00+00:00")
    belief_time_2 = pd.Timestamp("2021-03-27 09:00:00+00:00")
    belief_time_3 = pd.Timestamp("2021-03-27 10:00:00+00:00")

    initial_beliefs = tb.BeliefsDataFrame(
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
    save_to_db(initial_beliefs, save_changed_beliefs_only=False)
    db.session.commit()

    candidate_belief = tb.BeliefsDataFrame(
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
    save_to_db(candidate_belief, save_changed_beliefs_only=True)
    db.session.commit()

    beliefs = sensor.search_beliefs(
        source=source,
        most_recent_beliefs_only=False,
        event_starts_after=event_start - pd.Timedelta(minutes=1),
        event_ends_before=event_start + sensor.event_resolution,
    )
    beliefs = beliefs[beliefs.event_starts == event_start]
    belief_values_by_time = {
        bt.isoformat(): value
        for bt, value in zip(beliefs.belief_times, beliefs.event_value)
    }
    assert len(belief_values_by_time) == 3
    assert belief_values_by_time[belief_time_3.isoformat()] == 2.0


def test_drop_unchanged_helper_uses_wrong_prior_when_belief_times_descending(
    setup_beliefs, db
):
    """Regression: candidate should compare against latest prior, not older prior."""

    sensor = get_test_sensor(db)
    assert sensor is not None
    source = DataSource(name="Drop unchanged direct helper repro", type="demo script")
    db.session.add(source)
    db.session.commit()

    event_start = pd.Timestamp("2021-03-28 16:00:00+00:00")
    belief_time_1 = pd.Timestamp("2021-03-27 08:00:00+00:00")  # older
    belief_time_2 = pd.Timestamp("2021-03-27 09:00:00+00:00")  # latest prior
    belief_time_3 = pd.Timestamp("2021-03-27 10:00:00+00:00")  # candidate

    bdf_db = tb.BeliefsDataFrame(
        [
            TimedBelief(
                sensor=sensor,
                source=source,
                event_start=event_start,
                belief_time=belief_time_2,
                event_value=1.0,
            ),
            TimedBelief(
                sensor=sensor,
                source=source,
                event_start=event_start,
                belief_time=belief_time_1,
                event_value=2.0,
            ),
        ]
    )
    bdf_db = bdf_db.sort_index(ascending=False)
    assert list(bdf_db.belief_times) == [belief_time_2, belief_time_1]

    candidate = tb.BeliefsDataFrame(
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
    assert len(filtered) == 1
