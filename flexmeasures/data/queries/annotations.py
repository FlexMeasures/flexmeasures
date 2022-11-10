from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy.orm import Query

from flexmeasures.data.models.annotations import (
    Annotation,
    GenericAssetAnnotationRelationship,
)
from flexmeasures.data.models.data_sources import DataSource


def query_asset_annotations(
    asset_id: int,
    annotations_after: Optional[datetime] = None,
    annotations_before: Optional[datetime] = None,
    sources: Optional[List[DataSource]] = None,
    annotation_type: str | None = None,
) -> Query:
    """Match annotations assigned to the given asset."""
    query = Annotation.query.join(GenericAssetAnnotationRelationship).filter(
        GenericAssetAnnotationRelationship.generic_asset_id == asset_id,
        GenericAssetAnnotationRelationship.annotation_id == Annotation.id,
    )
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
