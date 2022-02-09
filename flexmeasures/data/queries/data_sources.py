from __future__ import annotations

from typing import Union, Optional

from flask import current_app
from flexmeasures import User
from flexmeasures.data import db
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.user import is_user


def get_or_create_source(
    source: Union[User, str],
    source_type: Optional[str] = None,
    model: Optional[str] = None,
    flush: bool = True,
) -> DataSource:
    if is_user(source):
        source_type = "user"
    query = DataSource.query.filter(DataSource.type == source_type)
    if model is not None:
        query = query.filter(DataSource.model == model)
    if is_user(source):
        query = query.filter(DataSource.user == source)
    elif isinstance(source, str):
        query = query.filter(DataSource.name == source)
    else:
        raise TypeError("source should be of type User or str")
    _source = query.one_or_none()
    if not _source:
        if is_user(source):
            _source = DataSource(user=source, model=model)
        else:
            if source_type is None:
                raise TypeError("Please specify a source type")
            _source = DataSource(name=source, model=model, type=source_type)
        current_app.logger.info(f"Setting up {_source} as new data source...")
        db.session.add(_source)
        if flush:
            # assigns id so that we can reference the new object in the current db session
            db.session.flush()
    return _source


def get_source_or_none(source: int, source_type: str) -> Optional[DataSource]:
    query = DataSource.query.filter(DataSource.type == source_type)
    query = query.filter(DataSource.id == int(source))
    return query.one_or_none()
