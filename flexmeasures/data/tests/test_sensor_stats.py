"""Tests for the statistics reported per data source, and for the entry combining them."""

from datetime import timedelta

import pandas as pd

from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.data.services.sensors import ALL_SOURCES_KEY, get_sensor_stats
from flexmeasures.tests.utils import get_test_sensor


def make_sensor(db, name: str, values_per_source: dict[str, list[float]]) -> Sensor:
    """Set up a sensor recording the given values, one source per key.

    Values are laid out on consecutive hours, so that a source's first and last event are predictable.
    """
    sensor = Sensor(
        name=name,
        generic_asset=get_test_sensor(db).generic_asset,
        event_resolution=timedelta(hours=1),
        unit="MW",
    )
    db.session.add(sensor)
    for source_name, values in values_per_source.items():
        source = DataSource(name=source_name, type="demo script")
        db.session.add(source)
        for hour, value in enumerate(values):
            db.session.add(
                TimedBelief(
                    sensor=sensor,
                    source=source,
                    event_start=pd.Timestamp("2021-03-28 00:00+00")
                    + pd.Timedelta(hours=hour),
                    belief_horizon=timedelta(0),
                    event_value=value,
                )
            )
    db.session.commit()
    return sensor


def stats_for(sensor: Sensor) -> dict:
    return get_sensor_stats(sensor, "", "", from_cache=False)


def test_the_combined_entry_summarises_every_source(setup_beliefs, db):
    """The combined entry must report the sources' data as if it came from one source."""
    sensor = make_sensor(
        db,
        "two sources",
        {
            "Combining source A": [1.0, 2.0, 3.0],
            "Combining source B": [10.0, 20.0],
        },
    )

    combined = stats_for(sensor)[ALL_SOURCES_KEY]

    assert combined["Number of values"] == 5
    assert combined["Sum over values"] == 36.0
    assert combined["Mean value"] == 36.0 / 5
    assert combined["Min value"] == 1.0
    assert combined["Max value"] == 20.0
    # Source A alone runs an hour longer, so the combined entry must end where it does.
    assert combined["First event start"] == "2021-03-28T00:00:00+00:00"
    assert combined["Last event end"] == "2021-03-28T03:00:00+00:00"


def test_the_combined_mean_leaves_nan_rows_out(setup_beliefs, db):
    """The combined mean must divide by the values it summed, not by the reported row count.

    "Number of values" counts NaN rows too, while "Sum over values" leaves them out,
    so weighting each source's mean by that count understates the combined mean.
    Here that naive weighting gives 3.375 rather than 4.0.
    """
    sensor = make_sensor(
        db,
        "a source with a NaN",
        {
            "NaN source A": [1.0, 2.0, float("nan")],
            "NaN source B": [9.0],
        },
    )

    stats = stats_for(sensor)
    combined = stats[ALL_SOURCES_KEY]

    # The NaN row is counted, but contributes to no value aggregate.
    assert combined["Number of values"] == 4
    assert combined["Sum over values"] == 12.0

    assert combined["Mean value"] == 12.0 / 3
    naive_mean = sum(
        record["Mean value"] * record["Number of values"]
        for source, record in stats.items()
        if source != ALL_SOURCES_KEY
    ) / sum(
        record["Number of values"]
        for source, record in stats.items()
        if source != ALL_SOURCES_KEY
    )
    assert combined["Mean value"] != naive_mean


def test_a_source_recording_only_nan_still_summarises(setup_beliefs, db):
    """A source with no value aggregates at all must not take the combined entry down with it."""
    sensor = make_sensor(
        db,
        "an all-NaN source",
        {
            "All-NaN source": [float("nan"), float("nan")],
            "Ordinary source": [4.0],
        },
    )

    stats = stats_for(sensor)

    # The all-NaN source reports its rows, but has no value aggregates to report.
    all_nan = next(
        record
        for source, record in stats.items()
        if source.startswith("All-NaN source (ID: ")
    )
    assert all_nan["Number of values"] == 2
    assert all_nan["Sum over values"] is None
    assert all_nan["Mean value"] is None

    combined = stats[ALL_SOURCES_KEY]
    assert combined["Number of values"] == 3
    assert combined["Sum over values"] == 4.0
    assert combined["Mean value"] == 4.0
    assert combined["Min value"] == 4.0
    assert combined["Max value"] == 4.0


def test_a_single_source_gets_no_combined_entry(setup_beliefs, db):
    """With one source there is nothing to combine, so the entry would only repeat that source."""
    sensor = make_sensor(db, "one source", {"Lonely source": [1.0, 2.0]})

    stats = stats_for(sensor)

    assert ALL_SOURCES_KEY not in stats
    assert len(stats) == 1
