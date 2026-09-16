"""
Utils around the data models and db sessions
"""

from __future__ import annotations

import functools
import re
from pathlib import Path

from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from alembic.script.revision import RevisionError
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from dataclasses import dataclass
from flask import current_app
from timely_beliefs import BeliefsDataFrame, BeliefsSeries
from sqlalchemy import select

from flexmeasures.data import db
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.time_series import TimedBelief, Sensor
from flexmeasures.data.services.time_series import drop_unchanged_beliefs

SAVE_TO_DB_SUCCESS = "success"
SAVE_TO_DB_SUCCESS_WITH_UNCHANGED_BELIEFS_SKIPPED = (
    "success_with_unchanged_beliefs_skipped"
)
SAVE_TO_DB_SUCCESS_BUT_NOTHING_NEW = "success_but_nothing_new"
SAVE_TO_DB_SUCCESS_STATUSES = (
    SAVE_TO_DB_SUCCESS,
    SAVE_TO_DB_SUCCESS_WITH_UNCHANGED_BELIEFS_SKIPPED,
    SAVE_TO_DB_SUCCESS_BUT_NOTHING_NEW,
)
SAVE_TO_DB_SUCCESS_WITH_CHANGES_STATUSES = (
    SAVE_TO_DB_SUCCESS,
    SAVE_TO_DB_SUCCESS_WITH_UNCHANGED_BELIEFS_SKIPPED,
)
TEMPLATE_COPY_GUIDANCE_PREFIX = "Copy this"

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
VERSIONS_CURRENT_DIR = MIGRATIONS_DIR / "versions_current"
VERSIONS_LEGACY_DIR = MIGRATIONS_DIR / "versions_legacy"

# Head of the frozen legacy revision tree, which the squash baseline replaces.
# It is a literal because that tree never gains another revision.
LEGACY_HEAD = "c7a2f13b9e04"

# Root of the current revision tree, i.e. the squash baseline.
# It is a literal because the current tree's root never changes, only its head does
# as new revisions are added; `test_migration_trees.py` reads the tree from disk to check it.
SQUASH_BASELINE = "812621895c9c"

# Matches a `revision = "abc123"` (or single-quoted) assignment line, capturing the id.
_REVISION_LINE = re.compile(r"""^revision\s*=\s*["']([^"']+)["']""", re.MULTILINE)


@dataclass(frozen=True)
class DatabaseSchemaRevisionStatus:
    """Alembic revision status for the connected database."""

    current_heads: tuple[str, ...]
    expected_heads: tuple[str, ...]
    inspection_error: str | None = None

    @property
    def is_migrated_to_head(self) -> bool:
        return (
            self.inspection_error is None
            and bool(self.current_heads)
            and self.current_heads == self.expected_heads
        )


def _read_revision_id(path: Path) -> str:
    """Read a revision module's own revision id, without importing it.

    Importing a revision module executes it, reading the file is what keeps app startup from paying that cost.
    """
    matches = _REVISION_LINE.findall(path.read_text(encoding="utf-8"))
    if not matches:
        raise ValueError(f"No `revision = ...` assignment found in {path}.")
    if len(matches) > 1:
        raise ValueError(f"Multiple `revision = ...` assignments found in {path}.")
    return matches[0]


def _current_tree_files() -> list[Path]:
    """Return the current tree's revision files, in filename order.

    Revision filenames are prefixed with their UTC creation timestamp (see `alembic.ini`'s
    `file_template`), so filename order is creation order, and the last file is the head.
    """
    return sorted(
        path
        for path in VERSIONS_CURRENT_DIR.glob("*.py")
        if not path.name.startswith("__")
    )


@functools.lru_cache(maxsize=1)
def get_current_tree_head() -> str | None:
    """Return the head revision of the current tree, read from the last filename.

    Returns None if the tree is empty, which only happens in a broken installation.
    """
    files = _current_tree_files()
    return _read_revision_id(files[-1]) if files else None


@functools.lru_cache(maxsize=1)
def get_current_tree_revisions() -> frozenset[str]:
    """Return every revision id in the current tree."""
    return frozenset(_read_revision_id(path) for path in _current_tree_files())


def _get_database_heads(app) -> tuple[tuple[str, ...], str | None]:
    """Return the database's current Alembic heads, plus a connectivity error if there was one."""
    from sqlalchemy.exc import OperationalError, ProgrammingError

    try:
        with app.app_context(), db.engine.connect() as connection:
            return (
                tuple(
                    sorted(MigrationContext.configure(connection).get_current_heads())
                ),
                None,
            )
    except OperationalError as exc:
        return (), str(exc)
    except ProgrammingError:
        # No alembic_version table yet, so this database has never been migrated.
        return (), None


def get_database_schema_revision_status(app) -> DatabaseSchemaRevisionStatus:
    """Return current and expected Alembic head revisions for the connected database.

    The expected head comes from the current tree's filenames rather than from an Alembic
    ScriptDirectory, because building one executes every revision module.
    A database that is still somewhere in the legacy tree simply is not at the expected head,
    which is the right answer: it does still need `flexmeasures db upgrade`.
    """
    if app.extensions.get("migrate") is None:
        return DatabaseSchemaRevisionStatus(current_heads=(), expected_heads=())

    head = get_current_tree_head()
    if head is None:
        return DatabaseSchemaRevisionStatus(current_heads=(), expected_heads=())
    expected_heads = (head,)

    current_heads, inspection_error = _get_database_heads(app)
    if inspection_error is not None:
        return DatabaseSchemaRevisionStatus(
            current_heads=(),
            expected_heads=expected_heads,
            inspection_error=inspection_error,
        )

    return DatabaseSchemaRevisionStatus(
        current_heads=current_heads,
        expected_heads=expected_heads,
    )


def database_schema_has_revision(app, required_revision: str) -> bool:
    """Return whether the connected database includes a specific Alembic revision.

    Since the squash, "includes" means one of two things.
    A database on the current tree has the squash baseline in its ancestry,
    and the baseline folds in every legacy revision up to `LEGACY_HEAD`,
    so any legacy revision is included by definition, at no cost.
    Any other revision, and any database still in the legacy tree, needs its ancestry walked,
    which is the one place where revision modules get executed.
    """
    revision_status = get_database_schema_revision_status(app)
    if (
        revision_status.inspection_error is not None
        or not revision_status.current_heads
    ):
        return False

    migrate_extension = app.extensions.get("migrate")
    if migrate_extension is None:
        return False

    current_tree_revisions = get_current_tree_revisions()
    if any(head in current_tree_revisions for head in revision_status.current_heads):
        if required_revision in current_tree_revisions:
            return True
        if _is_folded_into_baseline(required_revision):
            return True
        return False

    script = _script_directory_for(migrate_extension, VERSIONS_LEGACY_DIR)
    for current_head in revision_status.current_heads:
        try:
            revisions = script.revision_map.iterate_revisions(
                current_head,
                required_revision,
                inclusive=True,
                assert_relative_length=False,
            )
            if any(revision.revision == required_revision for revision in revisions):
                return True
        except RevisionError:
            continue
    return False


@functools.lru_cache(maxsize=1)
def get_legacy_tree_revisions() -> frozenset[str]:
    """Return every revision id in the legacy tree."""
    return frozenset(
        _read_revision_id(path)
        for path in VERSIONS_LEGACY_DIR.glob("*.py")
        if not path.name.startswith("__")
    )


def _is_folded_into_baseline(revision: str) -> bool:
    """Return whether a revision is one of the legacy revisions the baseline replaces.

    Every file in the legacy tree is an ancestor of `LEGACY_HEAD`, since that tree has a single
    head, so membership of the directory is the whole test, and it needs no imports.
    """
    return revision in get_legacy_tree_revisions()


def _script_directory_for(
    migrate_extension, version_locations: Path
) -> ScriptDirectory:
    """Build a ScriptDirectory over one revision tree.

    Note that this executes every revision module in that tree, so only call it when a migration is actually being run or planned.
    The config is built here rather than through Flask-Migrate, so that no app context is needed.
    """
    config = AlembicConfig()
    config.set_main_option("script_location", migrate_extension.directory)
    config.set_main_option("path_separator", "os")
    config.set_main_option("version_locations", str(version_locations))
    return ScriptDirectory.from_config(config)


def _flask_migrate_config(migrate, version_locations: Path) -> AlembicConfig:
    """Build Flask-Migrate's Alembic config, pointed at one revision tree.

    Unlike `_script_directory_for`, this goes through Flask-Migrate, so it reads `alembic.ini` and carries the `env.py` arguments that running a migration needs.
    It therefore requires an app context.
    """
    config = migrate.get_config()
    config.set_main_option("version_locations", str(version_locations))
    return config


def upgrade_database_schema(app) -> None:
    """Upgrade the database to the head of the current revision tree, across the squash cut.

    There are three cases, told apart by what `alembic_version` holds:

    1. No row at all: a fresh database, which is built from the squash baseline onwards.
       The legacy revision modules are never imported.
    2. A revision from the current tree: an ordinary upgrade within that tree.
    3. Anything else: a database still in the frozen legacy tree.
       It is first walked to `LEGACY_HEAD` over `versions_legacy/`, which leaves it with exactly
       the schema the baseline builds, so the baseline is then stamped rather than run.
       The stamp purges the legacy revision from `alembic_version` as it goes, because the two
       trees are disjoint roots and a non-purging stamp would leave both rows behind.
       Afterwards the current tree is upgraded as usual, for anything added after the baseline.
    """
    migrate = app.extensions["migrate"].migrate
    current_heads, _ = _get_database_heads(app)
    needs_legacy_tree = bool(current_heads) and not (
        set(current_heads) & get_current_tree_revisions()
    )

    if needs_legacy_tree:
        app.logger.info(
            "Database is still on the pre-squash revision tree "
            f"({', '.join(current_heads)}); upgrading it to {LEGACY_HEAD} first."
        )
        alembic_command.upgrade(
            _flask_migrate_config(migrate, VERSIONS_LEGACY_DIR), LEGACY_HEAD
        )
        app.logger.info(
            f"Schema is now equivalent to the squash baseline; stamping it as {SQUASH_BASELINE}."
        )
        alembic_command.stamp(
            _flask_migrate_config(migrate, VERSIONS_CURRENT_DIR),
            SQUASH_BASELINE,
            purge=True,
        )

    alembic_command.upgrade(
        _flask_migrate_config(migrate, VERSIONS_CURRENT_DIR), "head"
    )


def format_database_schema_revision_status(
    status: DatabaseSchemaRevisionStatus,
) -> str:
    """Format Alembic revisions for host-facing log messages."""

    def format_heads(heads: tuple[str, ...]) -> str:
        return ", ".join(heads) if heads else "unknown"

    return (
        f"current revision(s): {format_heads(status.current_heads)}; "
        f"head revision(s): {format_heads(status.expected_heads)}"
    )


def save_to_session(objects: list[db.Model], overwrite: bool = False):
    """
    Utility function to save to database, either efficiently with a bulk save, or inefficiently with a merge save.
    """
    if not overwrite:
        db.session.bulk_save_objects(objects)
    else:
        for o in objects:
            db.session.merge(o)


def get_data_source(
    data_source_name: str,
    data_source_model: str | None = None,
    data_source_version: str | None = None,
    data_source_type: str = "script",
) -> DataSource:
    """Make sure we have a data source. Create one if it doesn't exist, and add to session.
    Meant for scripts that may run for the first time.
    """

    data_source = db.session.execute(
        select(DataSource).filter_by(
            name=data_source_name,
            model=data_source_model,
            version=data_source_version,
            type=data_source_type,
        )
    ).scalar_one_or_none()
    if data_source is None:
        data_source = DataSource(
            name=data_source_name,
            model=data_source_model,
            version=data_source_version,
            type=data_source_type,
        )
        db.session.add(data_source)
        db.session.flush()  # populate the primary key attributes (like id) without committing the transaction
        current_app.logger.info(
            f'Session updated with new {data_source_type} data source "{data_source.__repr__()}".'
        )
    return data_source


def save_to_db(
    data: BeliefsDataFrame | BeliefsSeries | list[BeliefsDataFrame | BeliefsSeries],
    bulk_save_objects: bool = True,
    save_changed_beliefs_only: bool = True,
) -> str:
    """Save the timed beliefs to the database.

    Note: This function does not commit. It does, however, flush the session. Best to keep transactions short.

    We make the distinction between updating beliefs and replacing beliefs.

    # Updating beliefs

    An updated belief is a belief from the same source as some already saved belief, and about the same event,
    but with a later belief time. If it has a different event value, then it represents a changed belief.
    Note that it is possible to explicitly record unchanged beliefs (i.e. updated beliefs with a later belief time,
    but with the same event value), by setting save_changed_beliefs_only to False.

    # Replacing beliefs

    A replaced belief is a belief from the same source as some already saved belief,
    and about the same event and with the same belief time, but with a different event value.
    Replacing beliefs is not allowed, because messing with the history corrupts data lineage.
    Corrections should instead be recorded as updated beliefs.
    Servers in 'play' mode are exempt from this rule, to facilitate replaying simulations.

    :param data: BeliefsDataFrame (or a list thereof) to be saved
    :param bulk_save_objects: if True, objects are bulk saved with session.bulk_save_objects(),
                              which is quite fast but has several caveats, see:
                              https://docs.sqlalchemy.org/orm/persistence_techniques.html#bulk-operations-caveats
    :param save_changed_beliefs_only: if True, unchanged beliefs are skipped (updated beliefs are only stored if they represent changed beliefs)
                                      if False, all updated beliefs are stored
    :returns: status string, one of the following:
              - SAVE_TO_DB_SUCCESS: all beliefs were saved
              - SAVE_TO_DB_SUCCESS_WITH_UNCHANGED_BELIEFS_SKIPPED: not all beliefs represented a state change
              - SAVE_TO_DB_SUCCESS_BUT_NOTHING_NEW: no beliefs represented a state change
    """

    # Convert to list
    if not isinstance(data, list):
        timed_values_list = [data]
    else:
        timed_values_list = data

    status = SAVE_TO_DB_SUCCESS
    values_saved = 0
    for timed_values in timed_values_list:

        # Convert series to frame if needed
        if isinstance(timed_values, BeliefsSeries):
            timed_values = timed_values.rename("event_value").to_frame()

        # Don't save NaN event values to the database
        timed_values = timed_values.dropna(subset=["event_value"])

        if timed_values.empty:
            # Nothing to save
            continue

        len_before = len(timed_values)
        if save_changed_beliefs_only:

            # Drop beliefs that haven't changed
            timed_values = drop_unchanged_beliefs(timed_values)
            len_after = len(timed_values)
            if len_after < len_before:
                status = SAVE_TO_DB_SUCCESS_WITH_UNCHANGED_BELIEFS_SKIPPED

            # Work around bug in which groupby still introduces an index level, even though we asked it not to
            if None in timed_values.index.names:
                timed_values.index = timed_values.index.droplevel(None)

            if timed_values.empty:
                # No state changes among the beliefs
                current_app.logger.info("No changes needing to be saved to DB.")
                continue

        current_app.logger.info("SAVING DATA  ...")
        TimedBelief.add_to_session(
            session=db.session,
            beliefs_data_frame=timed_values,
            bulk_save_objects=bulk_save_objects,
            allow_overwrite=current_app.config.get(
                "FLEXMEASURES_ALLOW_DATA_OVERWRITE", False
            ),
        )
        values_saved += len(timed_values)
        current_app.logger.info(f"SAVED {len(timed_values)} values TO DB.")
    # Flush to bring up potential unique violations (due to attempting to replace beliefs)
    db.session.flush()

    if values_saved == 0:
        status = SAVE_TO_DB_SUCCESS_BUT_NOTHING_NEW
    return status


def get_downsample_function_and_value(kpi: dict, sensor: Sensor, values) -> tuple:
    """Reduce a sensor's values over a window to the single number a KPI shows.

    :param kpi:     The `sensors_to_show_as_kpis` entry, which may name a function.
    :param sensor:  The sensor the KPI describes, whose unit decides the default function.
    :param values:  One value per event, as the chart draws them, rather than one row per belief.
    :returns:       The function used, and the value it produced.
    """
    downsample_function = kpi.get("function", None)
    if downsample_function is None:
        if sensor.unit == "%":
            downsample_function = "mean"
        else:
            downsample_function = "sum"

    # An empty window has nothing to reduce, and sum() over none of it is not a KPI of zero cost.
    if len(values) == 0:
        return downsample_function, 0

    if downsample_function == "mean":
        downsample_value = values.mean()
    elif downsample_function == "max":
        downsample_value = values.max()
    elif downsample_function == "min":
        downsample_value = values.min()
    else:
        downsample_value = values.sum()
    return downsample_function, downsample_value
