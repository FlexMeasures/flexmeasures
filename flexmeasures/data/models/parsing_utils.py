from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from flask import current_app
from flexmeasures.data import db

from flexmeasures.data.models.data_sources import DataSource


def parse_source_arg_per_entry(
    source: (
        DataSource
        | int
        | str
        | Sequence[DataSource]
        | Sequence[int]
        | Sequence[str]
        | None
    ),
) -> list[list[DataSource]] | None:
    """Parse the "source" argument, keeping the sources of each entry together.

    One entry can name more than one source, because a name is not unique,
    and the sources it names arrive in no particular order.
    Callers that care which source is preferred should treat one entry as one preference,
    rather than reading an order into what a single name happened to match.

    Passes None as is (i.e. no source argument is given).
    """
    if source is None:
        return source
    if isinstance(source, (DataSource, str, int)):
        entries: Sequence = [source]
    else:
        entries = source
    parsed_entries: list[list[DataSource]] = []
    for entry in entries:
        if isinstance(entry, int):
            parsed_source = db.session.get(DataSource, entry)
            if parsed_source is None:
                current_app.logger.warning(
                    f"Beliefs searched for unknown source {entry}"
                )
                parsed_entries.append([])
            else:
                parsed_entries.append([parsed_source])
        elif isinstance(entry, str):
            named = db.session.scalars(select(DataSource).filter_by(name=entry)).all()
            if not named:
                current_app.logger.warning(
                    f"Beliefs searched for unknown source {entry}"
                )
            parsed_entries.append(list(named))
        else:
            parsed_entries.append([entry])
    return parsed_entries


def parse_source_arg(
    source: (
        DataSource
        | int
        | str
        | Sequence[DataSource]
        | Sequence[int]
        | Sequence[str]
        | None
    ),
) -> list[DataSource] | None:
    """Parse the "source" argument by looking up DataSources corresponding to any given ids or names.

    Passes None as is (i.e. no source argument is given).
    Accepts ids and names as list or tuples, always converting them to a list.
    """
    parsed_entries = parse_source_arg_per_entry(source)
    if parsed_entries is None:
        return None
    return [parsed_source for entry in parsed_entries for parsed_source in entry]
