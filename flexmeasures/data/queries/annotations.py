from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm.attributes import InstrumentedAttribute
from sqlalchemy.orm import Query

from flexmeasures.data.models.annotations import (
    Annotation,
    AccountAnnotationRelationship,
    GenericAssetAnnotationRelationship,
    SensorAnnotationRelationship,
)
from flexmeasures.data.models.data_sources import DataSource


def _query_related_annotations(
    relationship_model,
    related_id_column: InstrumentedAttribute,
    related_id: int,
    annotations_after: datetime | None = None,
    annotations_before: datetime | None = None,
    sources: list[DataSource] | None = None,
    annotation_type: str | None = None,
) -> Query:
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
    if sources:
        query = query.filter(Annotation.source.in_(sources))
    if annotation_type is not None:
        query = query.filter(Annotation.type == annotation_type)
    return query


def query_asset_annotations(
    asset_id: int,
    annotations_after: datetime | None = None,
    annotations_before: datetime | None = None,
    sources: list[DataSource] | None = None,
    annotation_type: str | None = None,
) -> Query:
    """Match annotations assigned to the given asset."""
    return _query_related_annotations(
        GenericAssetAnnotationRelationship,
        GenericAssetAnnotationRelationship.generic_asset_id,
        asset_id,
        annotations_after,
        annotations_before,
        sources,
        annotation_type,
    )


def query_account_annotations(
    account_id: int,
    annotations_after: datetime | None = None,
    annotations_before: datetime | None = None,
    sources: list[DataSource] | None = None,
    annotation_type: str | None = None,
) -> Query:
    """Match annotations assigned to the given account."""
    return _query_related_annotations(
        AccountAnnotationRelationship,
        AccountAnnotationRelationship.account_id,
        account_id,
        annotations_after,
        annotations_before,
        sources,
        annotation_type,
    )


def query_sensor_annotations(
    sensor_id: int,
    annotations_after: datetime | None = None,
    annotations_before: datetime | None = None,
    sources: list[DataSource] | None = None,
    annotation_type: str | None = None,
) -> Query:
    """Match annotations assigned to the given sensor."""
    return _query_related_annotations(
        SensorAnnotationRelationship,
        SensorAnnotationRelationship.sensor_id,
        sensor_id,
        annotations_after,
        annotations_before,
        sources,
        annotation_type,
    )
