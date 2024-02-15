from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from flask import current_app
from flexmeasures.data import db

from flexmeasures.data.models.data_sources import DataSource


def parse_source_arg(
    source: DataSource
    | int
    | str
    | Sequence[DataSource]
    | Sequence[int]
    | Sequence[str]
    | None,
) -> list[DataSource] | None:
    """Parse the "source" argument by looking up DataSources corresponding to any given ids or names.

    Passes None as is (i.e. no source argument is given).
    Accepts ids and names as list or tuples, always converting them to a list.
    """
    if source is None:
        return source
    if isinstance(source, (DataSource, str, int)):
        sources = [source]
    else:
        sources = source
    parsed_sources: list[DataSource] = []
    for source in sources:
        if isinstance(source, int):
            parsed_source = db.session.get(DataSource, source)
            if parsed_source is None:
                current_app.logger.warning(
                    f"Beliefs searched for unknown source {source}"
                )
            else:
                parsed_sources.append(parsed_source)
        elif isinstance(source, str):
            _parsed_sources = db.session.scalars(
                select(DataSource).filter_by(name=source)
            ).all()
            if _parsed_sources is []:
                current_app.logger.warning(
                    f"Beliefs searched for unknown source {source}"
                )
            else:
                parsed_sources.extend(_parsed_sources)
        else:
            parsed_sources.append(source)
    return parsed_sources
