from __future__ import annotations

import logging

from flask import current_app
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from typing import Type, TypeVar

from flexmeasures import Account, Source, User
from flexmeasures.data import db
from flexmeasures.data.models.data_sources import (
    DATA_SOURCE_UNIQUE_CONSTRAINT,
    DataSource,
    DataGenerator,
)
from flexmeasures.data.models.user import is_user
from flask import current_app as app

DG = TypeVar("DG", bound=DataGenerator)


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
                account=account,
            )
        current_app.logger.info(f"Setting up {_source} as new data source...")
        if flush:
            _source = _add_and_flush_source(_source, query)
        else:
            db.session.add(_source)
    return _source


def _add_and_flush_source(source: DataSource, query) -> DataSource:
    """Add and flush a new source, or return the identical source another transaction inserted since `query` looked for it."""
    # Flush anything else pending first, so that the savepoint below only concerns the new source.
    db.session.flush()
    try:
        with db.session.begin_nested():
            db.session.add(source)
            # Assigns an id, so that we can reference the new object in the current db session.
            db.session.flush()
    except IntegrityError as exc:
        if (
            getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
            != DATA_SOURCE_UNIQUE_CONSTRAINT
        ):
            raise
        # Another transaction inserted the same source since we looked it up, so use that one.
        return db.session.execute(query).scalar_one()
    return source


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
