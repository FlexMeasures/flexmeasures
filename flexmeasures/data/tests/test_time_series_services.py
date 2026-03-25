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


def test_save_duplicate_probabilistic_belief_with_different_cp(setup_beliefs, db):
    """Saving a duplicate probabilistic belief (same event_start/source/belief_time but different cp) should succeed.

    This tests that multiple cumulative probabilities for the same event can coexist.
    """

    # Get a probabilistic belief from the database
    sensor = get_test_sensor(db)
    bdf = sensor.search_beliefs(
        source="ENTSO-E",
        most_recent_beliefs_only=False,
    )
    # Filter to only probabilistic beliefs
    prob_bdf = bdf[
        bdf.index.get_level_values("cumulative_probability").isin([0.2, 0.5])
    ]
    assert not prob_bdf.empty

    # Create a new belief with different cp values but same event_start/source/belief_time
    # Get the first probabilistic belief and add a new cp value
    first_belief = prob_bdf.iloc[:1].copy()

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
    setup_beliefs, db, add_market_prices
):
    """Saving a probabilistic belief with same event_start/source/belief_time/cp but different event_value should raise an error.

    This tests that replacing beliefs (changing the history) is not allowed, even for probabilistic beliefs.
    """

    # Get a probabilistic belief from the database
    sensor = add_market_prices["epex_da"]
    assert sensor is not None

    bdf = sensor.search_beliefs(
        source="ENTSO-E",
        most_recent_beliefs_only=False,
    )
    # Filter to only probabilistic beliefs
    prob_bdf = bdf[
        bdf.index.get_level_values("cumulative_probability").isin([0.2, 0.5])
    ]
    assert not prob_bdf.empty

    # Modify the event value of the first belief
    modified_bdf = prob_bdf.iloc[:1].copy()
    modified_bdf.iloc[0, 0] = (
        modified_bdf.iloc[0, 0] + 999
    )  # Change the value significantly

    # Try to save this modified belief - it should raise an IntegrityError
    with pytest.raises(IntegrityError):
        save_to_db(modified_bdf, save_changed_beliefs_only=False)
        db.session.flush()  # Force the error to be raised

    # Rollback the session to clean up after the failed transaction
    db.session.rollback()
