"""Dropping unchanged beliefs when a save holds several belief times for the same event (#2686)."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd
import pytest
import timely_beliefs as tb

from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.utils import save_to_db

EVENT_START = pd.Timestamp("2026-01-01T05:00:00+00:00")


def at(hhmm: str) -> pd.Timestamp:
    return pd.Timestamp(f"2026-01-01T{hhmm}:00+00:00")


@pytest.fixture
def sensor_and_source(fresh_db):
    asset_type = GenericAssetType(name="forecast target")
    asset = GenericAsset(name="forecast target", generic_asset_type=asset_type)
    sensor = Sensor(
        name="forecast target",
        generic_asset=asset,
        event_resolution=timedelta(hours=1),
        unit="MW",
    )
    source = DataSource(name="forecaster", type="forecaster")
    fresh_db.session.add_all([asset_type, asset, sensor, source])
    fresh_db.session.commit()
    return sensor, source


def frame(
    sensor: Sensor,
    source: DataSource,
    beliefs: list[tuple[str, float]],
    by_horizon: bool,
) -> tb.BeliefsDataFrame:
    """Deterministic beliefs about one event, given as (belief time, value) pairs."""
    bdf = tb.BeliefsDataFrame(
        [
            tb.TimedBelief(
                sensor=sensor,
                source=source,
                event_start=EVENT_START,
                belief_time=at(belief_time),
                event_value=value,
            )
            for belief_time, value in beliefs
        ]
    )
    # Producers hand over frames indexed either way, and both must be judged alike.
    return bdf.convert_index_from_belief_time_to_horizon() if by_horizon else bdf


def stored(sensor: Sensor) -> list[tuple[str, float]]:
    """Every belief on record about the event, as (belief time, value) pairs in belief-time order."""
    bdf = sensor.search_beliefs(
        most_recent_beliefs_only=False
    ).convert_index_from_belief_horizon_to_time()
    return sorted(
        (belief_time.strftime("%H:%M"), value)
        for belief_time, value in zip(bdf.belief_times, bdf["event_value"])
    )


def known_at(sensor: Sensor, hhmm: str) -> float:
    """The value a lookup of the most recent belief before the given time returns."""
    bdf = sensor.search_beliefs(beliefs_before=at(hhmm), most_recent_beliefs_only=True)
    assert len(bdf) == 1, bdf
    return bdf["event_value"].iloc[0]


by_time_and_by_horizon = pytest.mark.parametrize(
    "by_horizon", [False, True], ids=["indexed-by-belief-time", "indexed-by-horizon"]
)


@by_time_and_by_horizon
def test_a_value_that_changes_back_within_one_save_is_kept(
    fresh_db, sensor_and_source, by_horizon
):
    """A value that changes and changes back within one save is a change, not a repeat of an earlier belief.

    The last 10 differs from the 12 right before it, so it has to be kept,
    or a lookup at 02:30 returns the 12 the source had already moved away from.
    """
    sensor, source = sensor_and_source
    save_to_db(
        frame(
            sensor,
            source,
            [("00:00", 10.0), ("01:00", 12.0), ("02:00", 10.0)],
            by_horizon,
        )
    )
    fresh_db.session.commit()

    assert stored(sensor) == [("00:00", 10.0), ("01:00", 12.0), ("02:00", 10.0)]
    assert known_at(sensor, "02:30") == 10.0


@by_time_and_by_horizon
def test_a_value_that_changes_back_across_two_saves_is_kept(
    fresh_db, sensor_and_source, by_horizon
):
    """A belief is compared with the belief right before it, also when that belief arrives in the same save.

    The stored 10 is not the belief right before the new 10: the 12 in the same save is.
    """
    sensor, source = sensor_and_source
    save_to_db(frame(sensor, source, [("00:00", 10.0)], by_horizon))
    fresh_db.session.commit()
    save_to_db(frame(sensor, source, [("01:00", 12.0), ("02:00", 10.0)], by_horizon))
    fresh_db.session.commit()

    assert stored(sensor) == [("00:00", 10.0), ("01:00", 12.0), ("02:00", 10.0)]
    assert known_at(sensor, "02:30") == 10.0


@by_time_and_by_horizon
def test_beliefs_saved_one_at_a_time_keep_their_changes(
    fresh_db, sensor_and_source, by_horizon
):
    """Saving one belief time per save already worked; this keeps it that way."""
    sensor, source = sensor_and_source
    for belief in [("00:00", 10.0), ("01:00", 12.0), ("02:00", 10.0)]:
        save_to_db(frame(sensor, source, [belief], by_horizon))
        fresh_db.session.commit()

    assert stored(sensor) == [("00:00", 10.0), ("01:00", 12.0), ("02:00", 10.0)]
    assert known_at(sensor, "02:30") == 10.0


@by_time_and_by_horizon
def test_of_repeated_beliefs_in_one_save_the_earliest_is_kept(
    fresh_db, sensor_and_source, by_horizon
):
    """Of a run of equal beliefs, the earliest is kept, so the value is known from the moment it was first believed.

    Keeping the latest instead would leave nothing known before it,
    which is what a single save indexed by horizon did before #1918.
    """
    sensor, source = sensor_and_source
    save_to_db(
        frame(
            sensor,
            source,
            [("00:00", 10.0), ("01:00", 10.0), ("02:00", 12.0), ("03:00", 12.0)],
            by_horizon,
        )
    )
    fresh_db.session.commit()

    assert stored(sensor) == [("00:00", 10.0), ("02:00", 12.0)]
    assert known_at(sensor, "00:30") == 10.0
    assert known_at(sensor, "03:30") == 12.0


def test_a_probabilistic_belief_that_changes_back_within_one_save_is_kept(
    fresh_db, sensor_and_source
):
    """A probabilistic belief is compared as a whole with the belief right before it, also within one save."""
    sensor, source = sensor_and_source
    distributions = {
        "00:00": {0.1587: 9.0, 0.5: 10.0, 0.8413: 11.0},
        "01:00": {0.1587: 9.0, 0.5: 12.0, 0.8413: 11.0},  # only the median changed
        "02:00": {0.1587: 9.0, 0.5: 10.0, 0.8413: 11.0},  # and changed back
    }
    bdf = tb.BeliefsDataFrame(
        [
            tb.TimedBelief(
                sensor=sensor,
                source=source,
                event_start=EVENT_START,
                belief_time=at(belief_time),
                cumulative_probability=cp,
                event_value=value,
            )
            for belief_time, distribution in distributions.items()
            for cp, value in distribution.items()
        ]
    )
    save_to_db(bdf)
    fresh_db.session.commit()

    belief_times_on_record = sorted({belief_time for belief_time, _ in stored(sensor)})
    assert belief_times_on_record == ["00:00", "01:00", "02:00"]
    # Each belief is kept whole, not just the probability whose value changed.
    assert len(stored(sensor)) == 9


def test_a_deterministic_duplicate_saved_alongside_a_probabilistic_belief_is_dropped(
    fresh_db, sensor_and_source
):
    """A deterministic belief is recognised as unchanged also when the same save holds a probabilistic one.

    Saving it again at the same belief time would otherwise be taken for a different value,
    and refused as an overwrite.
    """
    sensor, source = sensor_and_source
    save_to_db(frame(sensor, source, [("00:00", 10.0)], by_horizon=False))
    fresh_db.session.commit()

    later_event = EVENT_START + sensor.event_resolution
    mixed = tb.BeliefsDataFrame(
        [
            # the same deterministic belief as stored
            tb.TimedBelief(
                sensor=sensor,
                source=source,
                event_start=EVENT_START,
                belief_time=at("00:00"),
                event_value=10.0,
            ),
        ]
        + [
            # a probabilistic belief about another event
            tb.TimedBelief(
                sensor=sensor,
                source=source,
                event_start=later_event,
                belief_time=at("00:00"),
                cumulative_probability=cp,
                event_value=value,
            )
            for cp, value in [(0.1587, 9.0), (0.5, 10.0), (0.8413, 11.0)]
        ]
    )
    save_to_db(mixed)
    fresh_db.session.commit()

    assert len(sensor.search_beliefs(most_recent_beliefs_only=False)) == 4


@pytest.mark.parametrize(
    "already_stored", [False, True], ids=["nothing-stored", "already-stored"]
)
@by_time_and_by_horizon
def test_an_exact_duplicate_within_one_save_is_saved_once(
    fresh_db, sensor_and_source, by_horizon, already_stored
):
    """A row that occurs twice in one save is saved once, rather than failing the save on the unique constraint.

    Reporters and aggregations that concatenate overlapping chunks hand over such frames.
    """
    from flexmeasures.data.services.time_series import drop_unchanged_beliefs

    sensor, source = sensor_and_source
    if already_stored:
        save_to_db(frame(sensor, source, [("01:00", 12.0)], by_horizon))
        fresh_db.session.commit()
    bdf = frame(sensor, source, [("00:00", 10.0), ("01:00", 12.0)], by_horizon)
    doubled = pd.concat([bdf, bdf.iloc[[-1]]])
    assert doubled.index.duplicated().any(), "the frame holds one row twice"

    assert not drop_unchanged_beliefs(doubled).index.duplicated().any()
    save_to_db(doubled)
    fresh_db.session.commit()

    assert stored(sensor) == [("00:00", 10.0), ("01:00", 12.0)]
