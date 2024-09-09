"""
Utils around the data models and db sessions
"""

from __future__ import annotations

from flask import current_app
from timely_beliefs import BeliefsDataFrame, BeliefsSeries
from sqlalchemy import select

from flexmeasures.data import db
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.time_series import TimedBelief
from flexmeasures.data.services.time_series import drop_unchanged_beliefs


def save_to_session(objects: list[db.Model], overwrite: bool = False):
    """Utility function to save to database, either efficiently with a bulk save, or inefficiently with a merge save."""
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
              - 'success': all beliefs were saved
              - 'success_with_unchanged_beliefs_skipped': not all beliefs represented a state change
              - 'success_but_nothing_new': no beliefs represented a state change
    """

    # Convert to list
    if not isinstance(data, list):
        timed_values_list = [data]
    else:
        timed_values_list = data

    status = "success"
    values_saved = 0
    for timed_values in timed_values_list:

        if timed_values.empty:
            # Nothing to save
            continue

        # Convert series to frame if needed
        if isinstance(timed_values, BeliefsSeries):
            timed_values = timed_values.rename("event_value").to_frame()

        len_before = len(timed_values)
        if save_changed_beliefs_only:

            # Drop beliefs that haven't changed
            timed_values = drop_unchanged_beliefs(timed_values)
            len_after = len(timed_values)
            if len_after < len_before:
                status = "success_with_unchanged_beliefs_skipped"

            # Work around bug in which groupby still introduces an index level, even though we asked it not to
            if None in timed_values.index.names:
                timed_values.index = timed_values.index.droplevel(None)

            if timed_values.empty:
                # No state changes among the beliefs
                continue

        current_app.logger.info("SAVING TO DB...")
        TimedBelief.add_to_session(
            session=db.session,
            beliefs_data_frame=timed_values,
            bulk_save_objects=bulk_save_objects,
            allow_overwrite=current_app.config.get(
                "FLEXMEASURES_ALLOW_DATA_OVERWRITE", False
            ),
        )
        values_saved += len(timed_values)
    # Flush to bring up potential unique violations (due to attempting to replace beliefs)
    db.session.flush()

    if values_saved == 0:
        status = "success_but_nothing_new"
    return status
