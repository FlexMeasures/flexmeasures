import pytest

from flexmeasures.data.models.reporting import Reporter

from datetime import datetime
from pytz import UTC


def test_get_reporter_from_source(db, app, aggregator_reporter_data_source):

    reporter = aggregator_reporter_data_source.data_generator

    assert isinstance(reporter, Reporter)
    assert reporter.__class__.__name__ == "TestReporter"

    res = reporter.compute(
        start=datetime(2023, 1, 1, tzinfo=UTC), end=datetime(2023, 1, 2, tzinfo=UTC)
    )

    assert res.lineage.sources[0] == reporter.data_source

    with pytest.raises(AttributeError):
        reporter.compute(start=datetime(2023, 1, 1, tzinfo=UTC), end="not a date")


def test_data_source(db, app, aggregator_reporter_data_source):
    TestTeporter = app.data_generators["reporter"].get("TestReporter")

    ds1 = TestTeporter(config={"sensor": 1})

    db.session.add(ds1.data_source)
    db.session.commit()

    ds2 = TestTeporter(config={"sensor": 1})

    assert ds1.data_source == ds2.data_source
    assert ds1.data_source.attributes.get("config") == ds2.data_source.attributes.get(
        "config"
    )

    ds3 = TestTeporter(config={"sensor": 2})

    assert ds3.data_source != ds2.data_source
    assert ds3.data_source.attributes.get("config") != ds2.data_source.attributes.get(
        "config"
    )
