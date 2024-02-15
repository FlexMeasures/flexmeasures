from __future__ import annotations

from flask import current_app
from sqlalchemy import select

from flexmeasures import User
from flexmeasures.data import db
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.user import is_user


def get_or_create_source(
    source: User | str,
    source_type: str | None = None,
    model: str | None = None,
    version: str | None = None,
    attributes: dict | None = None,
    flush: bool = True,
) -> DataSource:
    if is_user(source):
        source_type = "user"
    query = select(DataSource).filter(DataSource.type == source_type)
    if model is not None:
        query = query.filter(DataSource.model == model)
    if version is not None:
        query = query.filter(DataSource.version == version)
    if attributes is not None:
        query = query.filter(
            DataSource.attributes_hash == DataSource.hash_attributes(attributes)
        )
    if is_user(source):
        query = query.filter(DataSource.user == source)
    elif isinstance(source, str):
        query = query.filter(DataSource.name == source)
    else:
        raise TypeError("source should be of type User or str")
    _source = db.session.execute(query).scalar_one_or_none()
    if not _source:
        if is_user(source):
            _source = DataSource(user=source, model=model, version=version)
        else:
            if source_type is None:
                raise TypeError("Please specify a source type")
            _source = DataSource(
                name=source,
                model=model,
                version=version,
                type=source_type,
                attributes=attributes,
            )
        current_app.logger.info(f"Setting up {_source} as new data source...")
        db.session.add(_source)
        if flush:
            # assigns id so that we can reference the new object in the current db session
            db.session.flush()
    return _source


def get_source_or_none(
    source: int | str, source_type: str | None = None
) -> DataSource | None:
    """
    :param source:      source id
    :param source_type: optionally, filter by source type
    """
    query = select(DataSource)
    if source_type is not None:
        query = query.filter(DataSource.type == source_type)
    query = query.filter(DataSource.id == int(source))
    return db.session.execute(query).scalar_one_or_none()
