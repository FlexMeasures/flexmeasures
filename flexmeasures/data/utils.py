from typing import List, Optional

import click

from flexmeasures.data.config import db
from flexmeasures.data.models.data_sources import DataSource


def save_to_session(objects: List[db.Model], overwrite: bool = False):
    """Utility function to save to database, either efficiently with a bulk save, or inefficiently with a merge save."""
    if not overwrite:
        db.session.bulk_save_objects(objects)
    else:
        for o in objects:
            db.session.merge(o)


def get_data_source(
    data_source_name: str,
    data_source_model: Optional[str] = None,
    data_source_version: Optional[str] = None,
    data_source_type: str = "script",
) -> DataSource:
    """Make sure we have a data source. Create one if it doesn't exist, and add to session.
    Meant for scripts that may run for the first time.
    """

    data_source = DataSource.query.filter_by(
        name=data_source_name,
        model=data_source_model,
        version=data_source_version,
        type=data_source_type,
    ).one_or_none()
    if data_source is None:
        data_source = DataSource(
            name=data_source_name,
            model=data_source_model,
            version=data_source_version,
            type=data_source_type,
        )
        db.session.add(data_source)
        db.session.flush()  # populate the primary key attributes (like id) without committing the transaction
        click.echo(
            f'Session updated with new {data_source_type} data source "{data_source.__repr__()}".'
        )
    return data_source
