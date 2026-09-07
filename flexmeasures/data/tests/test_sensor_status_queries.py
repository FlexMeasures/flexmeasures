"""Tests for how the sensor status service looks up the most recent beliefs."""

from unittest import mock

import pandas as pd
from timely_beliefs import BeliefsDataFrame

from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.time_series import TimedBelief
from flexmeasures.data.services.sensors import _get_sensor_bdfs_by_source_type
from flexmeasures.data.utils import save_to_db
from flexmeasures.tests.utils import get_test_sensor


def add_belief(db, sensor, source_name: str, source_type: str) -> DataSource:
    """Record one belief for the sensor from a new source of the given type."""
    source = DataSource(name=source_name, type=source_type)
    db.session.add(source)
    db.session.commit()
    save_to_db(
        BeliefsDataFrame(
            [
                TimedBelief(
                    sensor=sensor,
                    source=source,
                    event_start=pd.Timestamp("2021-03-28 16:00:00+00:00"),
                    belief_time=pd.Timestamp("2021-03-27 08:00:00+00:00"),
                    event_value=1.0,
                )
            ]
        )
    )
    db.session.commit()
    return source


def test_only_source_types_that_recorded_are_queried(setup_beliefs, db):
    """A source type that never recorded for this sensor must not cost a belief query.

    Such a query cannot be answered from an index: it would walk the sensor's events,
    from the newest backwards, checking the type of every belief's source,
    and read all of them before concluding that this type recorded none.
    The sensor's sources are known from the summary table, so those types can be skipped entirely.
    """
    sensor = get_test_sensor(db)

    with mock.patch.object(
        TimedBelief, "search", wraps=TimedBelief.search
    ) as search_spy:
        bdfs = _get_sensor_bdfs_by_source_type(sensor=sensor, staleness_search={})

    # The fixture records beliefs from one source only, of type "demo script"
    assert set(bdfs) == {"demo script"}
    assert search_spy.call_count == 1

    # And that one query names its sources, rather than filtering on the type of the source
    kwargs = search_spy.call_args.kwargs
    assert "source_types" not in kwargs
    assert [source.type for source in kwargs["source"]] == ["demo script"]


def test_a_second_source_type_is_picked_up(setup_beliefs, db):
    """Adding a source of another type must add that type, and only that type, to the results."""
    sensor = get_test_sensor(db)
    add_belief(db, sensor, "A reporter", "reporter")

    with mock.patch.object(
        TimedBelief, "search", wraps=TimedBelief.search
    ) as search_spy:
        bdfs = _get_sensor_bdfs_by_source_type(sensor=sensor, staleness_search={})

    assert set(bdfs) == {"demo script", "reporter"}
    assert search_spy.call_count == 2


def test_source_filter_in_the_staleness_search_is_honoured(setup_beliefs, db):
    """A search restricted to one source must report on that source only.

    The source types are resolved before the beliefs are queried,
    so this filter has to be applied to that resolution as well.
    """
    sensor = get_test_sensor(db)
    reporter_source = add_belief(db, sensor, "The only source of interest", "reporter")

    bdfs = _get_sensor_bdfs_by_source_type(
        sensor=sensor, staleness_search=dict(source=[reporter_source])
    )

    assert set(bdfs) == {"reporter"}


def test_excluded_source_types_are_honoured(setup_beliefs, db):
    """An excluded source type must not be reported on, nor queried for."""
    sensor = get_test_sensor(db)
    add_belief(db, sensor, "An excluded reporter", "reporter")

    with mock.patch.object(
        TimedBelief, "search", wraps=TimedBelief.search
    ) as search_spy:
        bdfs = _get_sensor_bdfs_by_source_type(
            sensor=sensor, staleness_search=dict(exclude_source_types=["reporter"])
        )

    assert set(bdfs) == {"demo script"}
    assert search_spy.call_count == 1
