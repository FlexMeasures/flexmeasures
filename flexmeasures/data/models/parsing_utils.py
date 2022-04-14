from typing import Optional, Union, List

from flask import current_app
from flexmeasures.data import db

from flexmeasures.data.models.data_sources import DataSource


def parse_source_arg(
    source: Optional[
        Union[DataSource, List[DataSource], int, List[int], str, List[str]]
    ]
) -> Optional[List[DataSource]]:
    """Parse the "source" argument by looking up DataSources corresponding to any given ids or names."""
    if source is None:
        return source
    if not isinstance(source, list):
        sources = [source]
    else:
        sources = source
    parsed_sources: List[DataSource] = []
    for source in sources:
        if isinstance(source, int):
            parsed_source = (
                db.session.query(DataSource).filter_by(id=source).one_or_none()
            )
            if parsed_source is None:
                current_app.logger.warning(
                    f"Beliefs searched for unknown source {source}"
                )
            else:
                parsed_sources.append(parsed_source)
        elif isinstance(source, str):
            _parsed_sources = db.session.query(DataSource).filter_by(name=source).all()
            if _parsed_sources is []:
                current_app.logger.warning(
                    f"Beliefs searched for unknown source {source}"
                )
            else:
                parsed_sources.extend(_parsed_sources)
        else:
            parsed_sources.append(source)
    return parsed_sources
