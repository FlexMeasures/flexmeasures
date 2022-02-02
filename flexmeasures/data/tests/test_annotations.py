import pandas as pd

from flexmeasures.data.models.annotations import Annotation, get_or_create_annotation
from flexmeasures.data.models.data_sources import DataSource


def test_get_or_create_annotation(db):
    """Save an annotation, then get_or_create a new annotation with the same contents."""
    source = DataSource.query.first()
    first_annotation = Annotation(
        content="Dutch new year",
        start=pd.Timestamp("2020-01-01 00:00+01"),
        end=pd.Timestamp("2020-01-02 00:00+01"),
        source=source,
        type="holiday",
    )
    assert first_annotation == get_or_create_annotation(first_annotation)
    db.session.flush()
    second_annotation = Annotation(
        content="Dutch new year",
        start=pd.Timestamp("2020-01-01 00:00+01"),
        end=pd.Timestamp("2020-01-02 00:00+01"),
        source=source,
        type="holiday",
    )
    assert first_annotation == get_or_create_annotation(second_annotation)
