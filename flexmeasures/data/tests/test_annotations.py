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


def test_count_annotations(db, setup_annotations):
    """Regression test: GenericAsset.count_annotations executes its query rather than calling .count() on it directly.

    The query is a SQLAlchemy Select, which has no .count() method.
    """
    asset = setup_annotations["asset"]
    assert asset.count_annotations() == 1


def test_search_annotations_by_belief_time(db, setup_annotations):
    """search_annotations filters by belief time in both directions.

    Annotations without a belief_time (unknown recording moment, not necessarily
    a future one) are always kept, regardless of the beliefs_before/beliefs_after
    filter applied.
    """
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


def test_get_or_create_annotation_updates_end(db, setup_sources):
    """Extending an existing label must reuse its identity instead of violating it."""
    source = db.session.scalars(select(DataSource).limit(1)).first()
    deadline = pd.Timestamp("2030-01-16 08:00+01")
    fields = dict(
        content="Depart for work: 60% SoC by 08:00 (configured)",
        start=deadline - pd.Timedelta(minutes=15),
        belief_time=deadline - pd.Timedelta(days=1),
        source=source,
        type="label",
    )
    first, _ = get_or_create_annotation(Annotation(end=deadline, **fields))
    db.session.flush()
    original_id = first.id
    new_end = deadline + pd.Timedelta(minutes=15)
    updated, is_new = get_or_create_annotation(Annotation(end=new_end, **fields))
    db.session.flush()
    assert not is_new
    assert updated.id == original_id
    assert updated.end == new_end
    repeated, is_new = get_or_create_annotation(Annotation(end=new_end, **fields))
    db.session.flush()
    assert not is_new
    assert repeated.id == original_id


def test_get_or_create_annotation_preserves_distinct_belief_times(db, setup_sources):
    """Equal labels recorded at different belief times are distinct annotations."""
    source = db.session.scalars(select(DataSource).limit(1)).first()
    fields = dict(
        content="Configured EV target",
        start=pd.Timestamp("2030-01-16 07:45+01"),
        end=pd.Timestamp("2030-01-16 08:15+01"),
        source=source,
        type="label",
    )
    first, _ = get_or_create_annotation(
        Annotation(belief_time=pd.Timestamp("2030-01-15 08:00+01"), **fields)
    )
    db.session.flush()
    second, is_new = get_or_create_annotation(
        Annotation(belief_time=pd.Timestamp("2030-01-15 12:00+01"), **fields)
    )
    db.session.flush()
    assert is_new
    assert second.id != first.id


def test_get_or_create_annotation_without_prior_preserves_legacy_spans(
    db, setup_sources
):
    """NULL-prior labels with different ends can coexist and remain repeatable."""
    source = db.session.scalars(select(DataSource).limit(1)).first()
    start = pd.Timestamp("2030-01-16 07:45+01")
    fields = dict(
        content="Configured EV target without prior",
        start=start,
        belief_time=None,
        source=source,
        type="label",
    )
    first = Annotation(end=start + pd.Timedelta(minutes=15), **fields)
    second = Annotation(end=start + pd.Timedelta(minutes=30), **fields)
    # Seed valid pre-existing data: the unique constraint permits both NULLs.
    db.session.add_all([first, second])
    db.session.flush()
    first_id, second_id = first.id, second.id
    before = db.session.scalar(select(func.count()).select_from(Annotation))

    for existing in (first, second):
        repeated, is_new = get_or_create_annotation(
            Annotation(end=existing.end, **fields)
        )
        db.session.flush()
        assert not is_new
        assert repeated.id == existing.id
    assert first.end == start + pd.Timedelta(minutes=15)
    assert second.end == start + pd.Timedelta(minutes=30)
    assert db.session.scalar(select(func.count()).select_from(Annotation)) == before

    # A new end without a prior still represents a distinct span, as before.
    third, is_new = get_or_create_annotation(
        Annotation(end=start + pd.Timedelta(minutes=45), **fields)
    )
    db.session.flush()
    assert is_new
    assert third.id not in (first_id, second_id)
    assert db.session.scalar(select(func.count()).select_from(Annotation)) == before + 1
