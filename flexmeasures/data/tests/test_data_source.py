import pytest

from flexmeasures.data.models.reporting import Reporter
from flexmeasures.data.models.data_sources import DataGenerator

from datetime import datetime
from pytz import UTC


def test_get_reporter_from_source(db, app, aggregator_reporter_data_source):

    reporter = aggregator_reporter_data_source.data_generator

    assert isinstance(reporter, Reporter)
    assert reporter.__class__.__name__ == "TestReporter"

    print(aggregator_reporter_data_source.data_generator)

    res = reporter.compute(
        start=datetime(2023, 1, 1, tzinfo=UTC), end=datetime(2023, 1, 2, tzinfo=UTC)
    )

    assert res.lineage.sources[0] == reporter.data_source

    with pytest.raises(AttributeError):
        reporter.compute(start=datetime(2023, 1, 1, tzinfo=UTC), end="not a date")


def test_data_source(db, app):
    class TestDataGenerator(DataGenerator):
        pass

    ds1 = TestDataGenerator(config={"a": "b"})

    db.session.add(ds1.data_source)
    db.session.commit()

    ds2 = TestDataGenerator(config={"a": "b"})

    assert ds1.data_source == ds2.data_source
    assert ds1.data_source.attributes.get("config") == ds2.data_source.attributes.get(
        "config"
    )

    ds3 = TestDataGenerator(config={"a": "c"})

    assert ds3.data_source != ds2.data_source
    assert ds3.data_source.attributes.get("config") != ds2.data_source.attributes.get(
        "config"
    )
