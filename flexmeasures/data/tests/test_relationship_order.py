from sqlalchemy import Integer
from sqlalchemy.orm import configure_mappers

from flexmeasures.data import db


def test_collections_are_ordered_by_id(app):
    """Every collection of objects with an integer id lists them by id, that is, in creation order.

    Without an order, a collection lists its objects in whatever order the database returns them,
    which can change after an update, so that code taking an object by position could get a different one from one query to the next.
    """
    configure_mappers()
    unordered = []
    for mapper in db.Model.registry.mappers:
        for relationship in mapper.relationships:
            target_id = relationship.mapper.columns.get("id")
            if (
                relationship.uselist
                and target_id is not None
                and target_id.primary_key
                and isinstance(target_id.type, Integer)
                and not relationship.order_by
            ):
                unordered.append(f"{mapper.class_.__name__}.{relationship.key}")
    assert unordered == [], "collections without an order_by"
