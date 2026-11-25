from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, or_, select, Select
from sqlalchemy.orm.attributes import InstrumentedAttribute

from flexmeasures.data.models.annotations import (
    Annotation,
    AccountAnnotationRelationship,
    GenericAssetAnnotationRelationship,
    SensorAnnotationRelationship,
)
from flexmeasures.data.models.data_sources import DataSource


def filter_by_belief_time(
    query: Select[tuple[Annotation]],
    beliefs_after: datetime | None = None,
    beliefs_before: datetime | None = None,
) -> Select[tuple[Annotation]]:
    """Restrict a query to annotations recorded within the given belief-time window.

    Annotations without a belief time are never filtered out: a missing belief time
    means the recording moment is unknown, not that the annotation was recorded in
    the future.
    """
    if beliefs_after is not None:
        query = query.filter(
            or_(
                Annotation.belief_time.is_(None),
                Annotation.belief_time > beliefs_after,
            )
        )
    if beliefs_before is not None:
        query = query.filter(
            or_(
                Annotation.belief_time.is_(None),
                Annotation.belief_time <= beliefs_before,
            )
        )
    return query


def _query_related_annotations(
    relationship_model,
    related_id_column: InstrumentedAttribute,
    related_id: int,
    annotations_after: datetime | None = None,
    annotations_before: datetime | None = None,
    beliefs_after: datetime | None = None,
    beliefs_before: datetime | None = None,
    sources: list[DataSource] | None = None,
    annotation_type: str | None = None,
    most_recent_beliefs_only: bool = False,
) -> Select[tuple[Annotation]]:
    """Match annotations assigned through a relationship table.

    With ``most_recent_beliefs_only``, only the most recent version of each annotation is matched (see `keep_most_recent_versions`).
    The versions are compared before the time window and the type are applied,
    so a newer version that moved out of the window, or that changed its type, hides the older version rather than letting it show.
    """

    def related_query(*columns) -> Select:
        query = (
            select(*columns)
            .join(relationship_model)
            .filter(
                related_id_column == related_id,
                relationship_model.annotation_id == Annotation.id,
            )
        )
        query = filter_by_belief_time(query, beliefs_after, beliefs_before)
        if sources:
            query = query.filter(
                Annotation.source_id.in_([source.id for source in sources])
            )
        return query

    query = related_query(Annotation)
    if most_recent_beliefs_only:
        query = query.filter(
            Annotation.id.in_(keep_most_recent_versions(related_query(Annotation.id)))
        )
    if annotations_after is not None:
        query = query.filter(Annotation.end > annotations_after)
    if annotations_before is not None:
        query = query.filter(Annotation.start < annotations_before)
    if annotation_type is not None:
        query = query.filter(Annotation.type == annotation_type)
    return query


def keep_most_recent_versions(query: Select) -> Select:
    """Keep, of each annotation's versions in a query on annotation ids for one subject, only the most recent one.

    An annotation is identified by its subject, source and start,
    so versions of one annotation can differ in end, type and content (e.g. a finding that grows, escalates or is resolved).
    The most recent version is the one with the latest belief time;
    a version with a belief time is more recent than one without, and among versions without one, the higher id wins.
    The query must be limited to one subject (e.g. one sensor), which then completes the identity.
    The versions are ranked with a window function, which does what Postgres' DISTINCT ON does, in every version of SQLAlchemy we support.
    """
    ranked = query.add_columns(
        func.row_number()
        .over(
            partition_by=(Annotation.source_id, Annotation.start),
            order_by=(Annotation.belief_time.desc().nulls_last(), Annotation.id.desc()),
        )
        .label("version_rank")
    ).subquery()
    return select(ranked.c.id).where(ranked.c.version_rank == 1)


def query_asset_annotations(
    asset_id: int,
    annotations_after: datetime | None = None,
    annotations_before: datetime | None = None,
    beliefs_after: datetime | None = None,
    beliefs_before: datetime | None = None,
    sources: list[DataSource] | None = None,
    annotation_type: str | None = None,
    most_recent_beliefs_only: bool = False,
) -> Select[tuple[Annotation]]:
    """Match annotations assigned to the given asset."""
    return _query_related_annotations(
        GenericAssetAnnotationRelationship,
        GenericAssetAnnotationRelationship.generic_asset_id,
        asset_id,
        annotations_after=annotations_after,
        annotations_before=annotations_before,
        beliefs_after=beliefs_after,
        beliefs_before=beliefs_before,
        sources=sources,
        annotation_type=annotation_type,
        most_recent_beliefs_only=most_recent_beliefs_only,
    )


def query_account_annotations(
    account_id: int,
    annotations_after: datetime | None = None,
    annotations_before: datetime | None = None,
    beliefs_after: datetime | None = None,
    beliefs_before: datetime | None = None,
    sources: list[DataSource] | None = None,
    annotation_type: str | None = None,
    most_recent_beliefs_only: bool = False,
) -> Select[tuple[Annotation]]:
    """Match annotations assigned to the given account."""
    return _query_related_annotations(
        AccountAnnotationRelationship,
        AccountAnnotationRelationship.account_id,
        account_id,
        annotations_after=annotations_after,
        annotations_before=annotations_before,
        beliefs_after=beliefs_after,
        beliefs_before=beliefs_before,
        sources=sources,
        annotation_type=annotation_type,
        most_recent_beliefs_only=most_recent_beliefs_only,
    )


def query_sensor_annotations(
    sensor_id: int,
    annotations_after: datetime | None = None,
    annotations_before: datetime | None = None,
    beliefs_after: datetime | None = None,
    beliefs_before: datetime | None = None,
    sources: list[DataSource] | None = None,
    annotation_type: str | None = None,
    most_recent_beliefs_only: bool = False,
) -> Select[tuple[Annotation]]:
    """Match annotations assigned to the given sensor."""
    return _query_related_annotations(
        SensorAnnotationRelationship,
        SensorAnnotationRelationship.sensor_id,
        sensor_id,
        annotations_after=annotations_after,
        annotations_before=annotations_before,
        beliefs_after=beliefs_after,
        beliefs_before=beliefs_before,
        sources=sources,
        annotation_type=annotation_type,
        most_recent_beliefs_only=most_recent_beliefs_only,
    )
