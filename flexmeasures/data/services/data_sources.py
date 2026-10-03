from __future__ import annotations

import logging

from flask import current_app
from sqlalchemy import or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql import ColumnElement
from typing import Type, TypeVar

from flexmeasures import Account, Source, User
from flexmeasures.data import db
from flexmeasures.data.models.data_sources import (
    DATA_SOURCE_IDENTITY_EXPRESSIONS,
    DATA_SOURCE_UNIQUE_INDEX,
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
    if is_user(source):
        # A user's source takes its organisation from the user, so the user alone identifies it.
        query = query.filter(DataSource.user == source)
    elif isinstance(source, str):
        # The organisation is part of what identifies a source, including when there is none:
        # two organisations running the same data generator under the same configuration each record under their own source,
        # rather than sharing one because their configurations happen to hash alike.
        # Naming no organisation therefore looks for a source that belongs to none, which is what the host's own sources look like.
        query = query.filter(
            DataSource.name == source,
            (
                DataSource.account_id.is_(None)
                if account is None
                else DataSource.account == account
            ),
        )
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
            _source = add_and_flush_source(_source, query)
        else:
            db.session.add(_source)
    return _source


def add_and_flush_source(source: DataSource, query) -> DataSource:
    """Add and flush a new source, or return the identical source another transaction inserted since `query` looked for it.

    :param source:  the new data source, not yet added to the session
    :param query:   the lookup that found no such source, to fetch the one another transaction inserted in the meantime
    """
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
            != DATA_SOURCE_UNIQUE_INDEX
        ):
            raise
        # Another transaction inserted the same source since we looked it up, so use that one.
        winner = db.session.execute(query).scalar_one_or_none()
        if winner is None:
            # The index also counts NULL as equal to an empty string, which the lookup does not.
            raise
        return winner
    return source


# Keys holding a list of source IDs, such as the sources a sensor reference filters on.
SOURCE_ID_LIST_KEYS = ("sources", "user_source_ids")
# The key holding a single source ID, next to a "sensor" key (as in reporter inputs).
SOURCE_ID_KEY = "source"


def find_referenced_source_ids(value) -> set[int]:
    """Find the data source IDs referred to in a JSON-like value, such as the arguments of a job.

    Source IDs are recognised under the keys that hold them in sensor references and reporter inputs.
    """
    found: set[int] = set()
    if isinstance(value, (list, tuple)):
        for item in value:
            found |= find_referenced_source_ids(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            if key in SOURCE_ID_LIST_KEYS and isinstance(item, list):
                found |= {i for i in item if _is_id(i)}
            elif key == SOURCE_ID_KEY and "sensor" in value and _is_id(item):
                found.add(item)
            else:
                found |= find_referenced_source_ids(item)
    return found


def _is_id(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def find_duplicate_sources() -> dict[int, int]:
    """Find data sources identical to another, as the unique index on data sources defines them.

    Such duplicates can only exist in a database that predates that index, whose migration merges each group into one source.
    Which one that is has to be decided the same way here, because this is what tells a host, before they upgrade,
    which of their waiting jobs name a source that is about to go: the source that recorded most recently keeps its ID.
    Recency is the belief time rather than the event a belief is about, since a generator mostly records about the future.
    A host naming a source with `-x keep-source=<id>` turns one group around, which this cannot know about.

    Kept in step with `SURVIVOR_RANKING` in migration 7c4e1a9d2b58, which cannot import from here.

    :returns: the ID of each duplicate data source, mapped to the ID of the data source it will be merged into
    """
    duplicates = db.session.execute(text(f"""
            WITH recorded AS (
                SELECT ds.*,
                       (SELECT max(tb.event_start - tb.belief_horizon)
                          FROM timed_belief tb
                         WHERE tb.source_id = ds.id) AS last_recorded
                  FROM data_source ds
            )
            SELECT duplicate, keep FROM (
                SELECT id AS duplicate,
                       first_value(id) OVER (
                           PARTITION BY {', '.join(DATA_SOURCE_IDENTITY_EXPRESSIONS)}
                           ORDER BY last_recorded DESC NULLS LAST, id ASC
                       ) AS keep
                FROM recorded
            ) AS grouped
            WHERE duplicate <> keep
            """)).all()
    return dict(duplicates)


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


def _readable_asset_condition(readable_account_ids: list[int]) -> ColumnElement[bool]:
    """The assets the current user may read, as the asset's own access rules spell it out:
    those of an organisation they may read, and public ones, which every logged-in user may read.
    """
    from flexmeasures.data.models.generic_assets import GenericAsset

    return or_(
        GenericAsset.account_id.in_(readable_account_ids),
        GenericAsset.account_id.is_(None),
    )


def _usable_source_conditions(
    readable_account_ids: list[int],
) -> list[ColumnElement[bool]]:
    """The two conditions under which a data source is the current user's to work with.

    A source is theirs when it belongs to an organisation they may read,
    and theirs by proxy when an automation they may read computes under it,
    which is how a source they set up becomes theirs before it has recorded anything.
    """
    from flexmeasures.data.models.automations import Automation
    from flexmeasures.data.models.generic_assets import GenericAsset

    return [
        DataSource.account_id.in_(readable_account_ids),
        select(1)
        .select_from(Automation)
        .join(GenericAsset, Automation.asset_id == GenericAsset.id)
        .where(
            Automation.generator_id == DataSource.id,
            _readable_asset_condition(readable_account_ids),
        )
        .exists(),
    ]


def usable_source_filter() -> ColumnElement[bool] | None:
    """A condition selecting the data sources which are the current user's to work with.

    These are the sources they may reuse for an automation of their own, and the ones whose stored configuration they may read,
    which is a stronger thing to be allowed than reading what a source has computed: see `readable_source_filter`.

    Returns None to say that every source qualifies, which is what admin access amounts to.
    """
    readable_account_ids = get_readable_source_account_ids()
    if readable_account_ids is None:
        return None
    return or_(*_usable_source_conditions(readable_account_ids))


def readable_source_filter() -> ColumnElement[bool] | None:
    """A condition selecting the data sources the current user may read.

    On top of the sources which are theirs to work with (see `usable_source_filter`),
    this covers the sources which have recorded data on a sensor they may read,
    because "what computed this number?" is a fair question about data one is allowed to see.

    Returns None to say that every source is readable, which is what admin access amounts to.
    """
    from flexmeasures.data.models.data_sources import SensorDataSource
    from flexmeasures.data.models.generic_assets import GenericAsset
    from flexmeasures.data.models.time_series import Sensor

    readable_account_ids = get_readable_source_account_ids()
    if readable_account_ids is None:
        return None
    return or_(
        *_usable_source_conditions(readable_account_ids),
        select(1)
        .select_from(SensorDataSource)
        .join(Sensor, SensorDataSource.sensor_id == Sensor.id)
        .join(GenericAsset, Sensor.generic_asset_id == GenericAsset.id)
        .where(
            SensorDataSource.source_id == DataSource.id,
            _readable_asset_condition(readable_account_ids),
        )
        .exists(),
    )


def _source_matches(source: DataSource, condition: ColumnElement[bool] | None) -> bool:
    """Whether the given source is one of those the condition selects."""
    if condition is None:
        return True
    return bool(
        db.session.scalar(
            select(
                select(DataSource.id)
                .where(DataSource.id == source.id, condition)
                .exists()
            )
        )
    )


def user_may_read_source(source: DataSource) -> bool:
    """Whether the current user may read the given data source.

    See `readable_source_filter` for what makes a source readable.
    """
    return _source_matches(source, readable_source_filter())


def user_may_use_source(source: DataSource) -> bool:
    """Whether the given data source is the current user's to work with.

    See `usable_source_filter` for what that means, and why it is a stronger thing to be allowed than reading the source.
    """
    return _source_matches(source, usable_source_filter())
