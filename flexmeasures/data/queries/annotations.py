from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Query

from flexmeasures.data.models.annotations import (
    Annotation,
    GenericAssetAnnotationRelationship,
    SensorAnnotationRelationship,
)
from flexmeasures.data.models.data_sources import DataSource


def query_asset_annotations(
    asset_id: int,
    sensor_id: int,
    relationship_module,
    annotations_after: datetime | None = None,
    annotations_before: datetime | None = None,
    sources: list[DataSource] | None = None,
    annotation_type: str | None = None,
) -> Query:
    """Match annotations assigned to the given asset."""
    query = select(Annotation)
    if relationship_module is GenericAssetAnnotationRelationship:
        query = query.join(
            GenericAssetAnnotationRelationship,
            GenericAssetAnnotationRelationship.annotation_id == Annotation.id,
        ).filter(GenericAssetAnnotationRelationship.generic_asset_id == asset_id)
    else:
        query = query.join(
            SensorAnnotationRelationship,
            SensorAnnotationRelationship.annotation_id == Annotation.id,
        ).filter(SensorAnnotationRelationship.sensor_id == sensor_id)

    if annotations_after is not None:
        query = query.filter(
            Annotation.end > annotations_after,
        )
    if annotations_before is not None:
        query = query.filter(
            Annotation.start < annotations_before,
        )
    if sources:
        query = query.filter(
            Annotation.source.in_(sources),
        )
    if annotation_type is not None:
        query = query.filter(
            Annotation.type == annotation_type,
        )
    return query
