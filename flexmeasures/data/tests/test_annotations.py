import pandas as pd
from sqlalchemy import select, func

from flexmeasures.data.models.annotations import Annotation, get_or_create_annotation
from flexmeasures.data.models.data_sources import DataSource


def test_get_or_create_annotation(db, setup_sources):
    """Save an annotation, then get_or_create a new annotation with the same contents."""
    num_annotations_before = db.session.scalar(
        select(func.count()).select_from(Annotation)
    )
    source = db.session.scalars(select(DataSource).limit(1)).first()
    first_annotation = Annotation(
        content="Dutch new year",
        start=pd.Timestamp("2020-01-01 00:00+01"),
        end=pd.Timestamp("2020-01-02 00:00+01"),
        source=source,
        type="holiday",
    )
    assert first_annotation == get_or_create_annotation(first_annotation)
    num_annotations_intermediate = db.session.scalar(
        select(func.count()).select_from(Annotation)
    )
    assert num_annotations_intermediate == num_annotations_before + 1
    assert (
        db.session.execute(
            select(Annotation).filter_by(
                content=first_annotation.content,
                start=first_annotation.start,
                end=first_annotation.end,
                source=first_annotation.source,
                type=first_annotation.type,
            )
        ).scalar_one_or_none()
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
    num_annotations_after = db.session.scalar(select(func.count(Annotation.id)))
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
