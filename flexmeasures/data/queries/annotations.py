from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_, select, Select
from sqlalchemy.orm.attributes import InstrumentedAttribute

from flexmeasures.data.models.annotations import (
    Annotation,
    AccountAnnotationRelationship,
    GenericAssetAnnotationRelationship,
    SensorAnnotationRelationship,
)
from flexmeasures.data.models.data_sources import DataSource


def _filter_by_belief_time(
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
) -> Select[tuple[Annotation]]:
    """Match annotations assigned through a relationship table."""
    query = (
        select(Annotation)
        .join(relationship_model)
        .filter(
            related_id_column == related_id,
            relationship_model.annotation_id == Annotation.id,
        )
    )

    if annotations_after is not None:
        query = query.filter(Annotation.end > annotations_after)
    if annotations_before is not None:
        query = query.filter(Annotation.start < annotations_before)
    query = _filter_by_belief_time(query, beliefs_after, beliefs_before)
    if sources:
        query = query.filter(Annotation.source.in_(sources))
    if annotation_type is not None:
        query = query.filter(Annotation.type == annotation_type)
    return query


def query_asset_annotations(
    asset_id: int,
    annotations_after: datetime | None = None,
    annotations_before: datetime | None = None,
    beliefs_after: datetime | None = None,
    beliefs_before: datetime | None = None,
    sources: list[DataSource] | None = None,
    annotation_type: str | None = None,
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
    )


def query_account_annotations(
    account_id: int,
    annotations_after: datetime | None = None,
    annotations_before: datetime | None = None,
    beliefs_after: datetime | None = None,
    beliefs_before: datetime | None = None,
    sources: list[DataSource] | None = None,
    annotation_type: str | None = None,
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
    )


def query_sensor_annotations(
    sensor_id: int,
    annotations_after: datetime | None = None,
    annotations_before: datetime | None = None,
    beliefs_after: datetime | None = None,
    beliefs_before: datetime | None = None,
    sources: list[DataSource] | None = None,
    annotation_type: str | None = None,
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
    )
