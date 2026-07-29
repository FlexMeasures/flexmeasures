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
    result_annotation, is_new = get_or_create_annotation(first_annotation)
    assert result_annotation == first_annotation
    assert is_new is True
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
    result_annotation, is_new = get_or_create_annotation(second_annotation)
    assert result_annotation == first_annotation
    assert is_new is False
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


def test_search_annotations_by_belief_time(db, setup_annotations):
    """search_annotations should filter out annotations recorded after beliefs_before,
    while always keeping annotations without a belief_time (unknown recording moment,
    not necessarily a future one)."""
    account = setup_annotations["account"]
    asset = setup_annotations["asset"]
    sensor = setup_annotations["sensor"]
    source = setup_annotations["annotation"].source

    # This annotation is recorded well after the window we'll query with beliefs_before.
    late_annotation = Annotation(
        content="Recorded later",
        start=pd.Timestamp("2020-01-03 00:00+01"),
        end=pd.Timestamp("2020-01-04 00:00+01"),
        source=source,
        type="holiday",
        belief_time=pd.Timestamp("2020-02-01 00:00+01"),
    )
    # This annotation is recorded well before the window we'll query with beliefs_after.
    early_annotation = Annotation(
        content="Recorded earlier",
        start=pd.Timestamp("2020-01-05 00:00+01"),
        end=pd.Timestamp("2020-01-06 00:00+01"),
        source=source,
        type="holiday",
        belief_time=pd.Timestamp("2020-01-01 00:00+01"),
    )
    for obj in (account, asset, sensor):
        obj.annotations.append(late_annotation)
        obj.annotations.append(early_annotation)
    db.session.flush()

    beliefs_before = pd.Timestamp("2020-01-15 00:00+01")
    for obj in (account, asset, sensor):
        annotations = obj.search_annotations(beliefs_before=beliefs_before)
        contents = {a.content for a in annotations}
        # The pre-existing "Dutch new year" annotation has belief_time=None,
        # so it should still be returned.
        assert "Dutch new year" in contents
        # The late annotation was recorded after beliefs_before, so it should be excluded.
        assert "Recorded later" not in contents

        # Without a beliefs_before filter, both annotations are returned.
        all_annotations = obj.search_annotations()
        all_contents = {a.content for a in all_annotations}
        assert {"Dutch new year", "Recorded later"} <= all_contents

    beliefs_after = pd.Timestamp("2020-01-15 00:00+01")
    for obj in (account, asset, sensor):
        annotations = obj.search_annotations(beliefs_after=beliefs_after)
        contents = {a.content for a in annotations}
        # The pre-existing "Dutch new year" annotation has belief_time=None,
        # so it should still be returned.
        assert "Dutch new year" in contents
        # The late annotation was recorded after beliefs_after, so it should be included.
        assert "Recorded later" in contents
        # The early annotation was recorded before beliefs_after, so it should be excluded.
        assert "Recorded earlier" not in contents

        # Without a beliefs_after filter, both the late and early annotations are returned.
        all_annotations = obj.search_annotations()
        all_contents = {a.content for a in all_annotations}
        assert {"Dutch new year", "Recorded later", "Recorded earlier"} <= all_contents
