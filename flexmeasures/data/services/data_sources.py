from __future__ import annotations

import logging

from flask import current_app
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql import Select
from typing import Type, TypeVar

from flexmeasures import Account, Source, User
from flexmeasures.data import db
from flexmeasures.data.models.data_sources import DataSource, DataGenerator
from flexmeasures.data.models.user import is_user
from flask import current_app as app


DG = TypeVar("DG", bound=DataGenerator)


def get_first_matching_source(query: Select) -> DataSource | None:
    """Return the matching data source with the lowest id, or None if there is no match.

    Tolerating multiple matches is a form of defense in depth:
    while uniqueness of data sources is enforced at the database level,
    a database may already contain (near-)duplicate rows from before that enforcement
    (for example, rows created by concurrently running jobs on a fresh database,
    or rows that differ only in fields the caller did not filter on, such as attributes).
    Rather than letting such rows fail every lookup with MultipleResultsFound,
    we deterministically pick the oldest row and log a warning.
    """
    sources = db.session.scalars(query.order_by(DataSource.id)).all()
    if len(sources) > 1:
        current_app.logger.warning(
            f"Found {len(sources)} data sources matching a lookup for one (the oldest is {sources[0]}); "
            f"using the one with the lowest id ({sources[0].id})."
        )
    return sources[0] if sources else None


def insert_source_race_safely(new_source: DataSource, query: Select) -> DataSource:
    """Insert a new data source, returning the winning row if we lose an insert race.

    The insert happens within a SAVEPOINT, so that losing a race against a concurrent
    session creating the same source (e.g. parallel workers scheduling against a fresh
    database, whose get-or-create logic all found no source yet) doesn't poison the
    enclosing transaction. Committing the savepoint flushes, which assigns an id so
    that the new source can be referenced in the current db session.

    :param new_source: the (not yet added) data source to insert
    :param query:      the query with which to re-fetch the winning row,
                       should our insert hit a uniqueness conflict
    """
    try:
        with db.session.begin_nested():
            db.session.add(new_source)
    except IntegrityError:
        # We lost the race: another session created the same source concurrently
        # (the savepoint was rolled back). Fetch the winning row instead.
        winner = get_first_matching_source(query)
        if winner is None:
            raise
        return winner
    return new_source


def get_or_create_source(
    source: User | str,
    source_type: str | None = None,
    model: str | None = None,
    version: str | None = None,
    attributes: dict | None = None,
    account: Account | None = None,
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
    if account is not None:
        query = query.filter(DataSource.account == account)
    if is_user(source):
        query = query.filter(DataSource.user == source)
    elif isinstance(source, str):
        query = query.filter(DataSource.name == source)
    else:
        raise TypeError("source should be of type User or str")
    _source = get_first_matching_source(query)
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
                account=account,
            )
        current_app.logger.info(f"Setting up {_source} as new data source...")
        _source = insert_source_race_safely(_source, query)
        if flush:
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


def get_data_generator(
    source: Source | None,
    model: str,
    config: dict,
    save_config: bool,
    data_generator_type: Type[DG],
) -> DG | None:
    dg_type_name = data_generator_type.__name__
    if source is None:
        logging.info(
            f"Looking for the {dg_type_name} {model} among all the registered {dg_type_name.lower()}s..."
        )

        # get data generator class
        data_generator_class: Type[DataGenerator] = app.data_generators.get(
            dg_type_name.lower()
        ).get(model)

        # check if it exists
        if data_generator_class is None:
            logging.error(f"{dg_type_name} class `{model}` not available.")
            return None

        logging.info(f"{dg_type_name} {model} found.")

        # initialize data generator class with the config
        data_generator: DataGenerator = data_generator_class(
            config=config, save_config=save_config
        )

    else:
        try:
            data_generator: DataGenerator = source.data_generator  # type: ignore

            if not isinstance(data_generator, data_generator_type):
                raise NotImplementedError(
                    f"DataGenerator `{data_generator}` is not of the type `{dg_type_name}`"
                )

            logging.info(
                f"{dg_type_name} `{data_generator.__class__.__name__}` fetched successfully from the database."
            )

        except NotImplementedError:
            logging.error(
                f"Error! DataSource `{source}` not storing a valid {dg_type_name}."
            )
            return None

        data_generator._save_config = save_config
    return data_generator
