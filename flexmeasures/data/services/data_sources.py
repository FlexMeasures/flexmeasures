from __future__ import annotations

import logging

from flask import current_app
from sqlalchemy import select
from typing import Type, TypeVar

from flexmeasures import Account, Source, User
from flexmeasures.data import db
from flexmeasures.data.models.data_sources import DataSource, DataGenerator
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


def get_readable_source_account_ids() -> list[int] | None:
    """Return the ids of the accounts whose data sources the current user may read.

    Returns None to say that every account's sources are readable, which is what admin access amounts to.
    """
    from flask_security import current_user

    from flexmeasures.auth.policy import user_has_admin_access, CONSULTANT_ROLE

    if user_has_admin_access(current_user, "read"):
        return None  # all sources
    readable_ids = [current_user.account_id]
    if current_user.has_role(CONSULTANT_ROLE):
        for client_account in current_user.account.consultancy_client_accounts:
            readable_ids.append(client_account.id)
    return readable_ids


def user_may_read_source(source: DataSource) -> bool:
    """Whether the current user may read the given data source.

    A source belonging to one of the user's own accounts is readable, and so is a system source,
    which is one that names neither an account nor a user.
    """
    readable_account_ids = get_readable_source_account_ids()
    if readable_account_ids is None:
        return True
    if source.account_id in readable_account_ids:
        return True
    return source.account_id is None and source.user_id is None
