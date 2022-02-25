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
    annotation_starts_after: Optional[datetime],
    annotation_ends_before: Optional[datetime],
    sources: List[DataSource],
    annotation_type: str = None,
) -> Query:
    """Match annotations assigned to the given asset."""
    query = Annotation.query.join(GenericAssetAnnotationRelationship).filter(
        GenericAssetAnnotationRelationship.generic_asset_id == asset_id,
        GenericAssetAnnotationRelationship.annotation_id == Annotation.id,
    )
    if annotation_starts_after is not None:
        query = query.filter(
            Annotation.start >= annotation_starts_after,
        )
    if annotation_ends_before is not None:
        query = query.filter(
            Annotation.end <= annotation_ends_before,
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
