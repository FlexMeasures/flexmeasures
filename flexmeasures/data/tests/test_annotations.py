import pandas as pd

from flexmeasures.data.models.annotations import Annotation, get_or_create_annotation
from flexmeasures.data.models.data_sources import DataSource


def test_get_or_create_annotation(db):
    """Save an annotation, then get_or_create a new annotation with the same contents."""
    num_annotations_before = Annotation.query.count()
    source = DataSource.query.first()
    first_annotation = Annotation(
        content="Dutch new year",
        start=pd.Timestamp("2020-01-01 00:00+01"),
        end=pd.Timestamp("2020-01-02 00:00+01"),
        source=source,
        type="holiday",
    )
    assert first_annotation == get_or_create_annotation(first_annotation)
    num_annotations_intermediate = Annotation.query.count()
    assert num_annotations_intermediate == num_annotations_before + 1
    assert (
        Annotation.query.filter(
            Annotation.content == first_annotation.content,
            Annotation.start == first_annotation.start,
            Annotation.end == first_annotation.end,
            Annotation.source == first_annotation.source,
            Annotation.type == first_annotation.type,
        ).one_or_none()
    ) == first_annotation
    assert first_annotation.id is not None
    second_annotation = Annotation(
        content="Dutch new year",
        start=pd.Timestamp("2020-01-01 00:00+01"),
        end=pd.Timestamp("2020-01-02 00:00+01"),
        source=source,
        type="holiday",
    )
    assert first_annotation == get_or_create_annotation(second_annotation)
    num_annotations_after = Annotation.query.count()
    assert num_annotations_after == num_annotations_intermediate
    assert second_annotation.id is None


def test_search_annotations(db, setup_annotations):
    account = setup_annotations["account"]
    asset = setup_annotations["asset"]
    sensor = setup_annotations["sensor"]
    for obj in (account, asset, sensor):
        annotations = getattr(obj, "search_annotations")()
        assert len(annotations) == 1
        assert annotations[0].content == "Dutch new year"
