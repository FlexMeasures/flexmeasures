from typing import List, Optional, Union

import click
from flask import current_app
from psycopg2.errors import UniqueViolation
from sqlalchemy.exc import IntegrityError
from timely_beliefs import BeliefsDataFrame

from flexmeasures.data import db
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.time_series import TimedBelief
from flexmeasures.data.services.time_series import drop_unchanged_beliefs


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


def save_to_db(
    data: Union[BeliefsDataFrame, List[BeliefsDataFrame]],
    save_changed_beliefs_only: bool = True,
    allow_overwrite: bool = False,
) -> str:
    """Save the timed beliefs to the database.

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
    Servers in 'play' mode are excempted from this rule, to facilitate replaying simulations.

    :param data: BeliefsDataFrame (or a list thereof) to be saved
    :param save_changed_beliefs_only: if True, unchanged beliefs are skipped (updated beliefs are only stored if they represent changed beliefs)
                                      if False, all updated beliefs are stored
    :param allow_overwrite:           if True, already stored beliefs may be replaced
                                      if False, already stored beliefs may not be replaced
    :returns: status string, one of the following:
              - 'success': all beliefs were saved
              - 'success_with_replacements': all beliefs were saved, (possibly) replacing pre-existing beliefs
              - 'success_with_unchanged_beliefs_skipped': not all beliefs represented a state change
              - 'failed_due_to_forbidden_replacements': no beliefs were saved, because replacing pre-existing beliefs is forbidden
    """

    # Convert to list
    if not isinstance(data, list):
        timed_values_list = [data]
    else:
        timed_values_list = data

    status = "success" if not allow_overwrite else "success_with_replacements"
    for timed_values in timed_values_list:

        if timed_values.empty:
            # Nothing to save
            continue

        len_before = len(timed_values)
        if save_changed_beliefs_only:

            # Drop beliefs that haven't changed
            timed_values = (
                timed_values.convert_index_from_belief_horizon_to_time()
                .groupby(level=["belief_time", "source"], as_index=False)
                .apply(drop_unchanged_beliefs)
            )
            len_after = len(timed_values)
            if len_after < len_before:
                status = "success_with_unchanged_beliefs_skipped"

            # Work around bug in which groupby still introduces an index level, even though we asked it not to
            if None in timed_values.index.names:
                timed_values.index = timed_values.index.droplevel(None)

            if timed_values.empty:
                # No state changes among the beliefs
                continue
        else:
            len_after = len_before

        current_app.logger.info("SAVING TO DB...")
        TimedBelief.add_to_session(
            session=db.session,
            beliefs_data_frame=timed_values,
            allow_overwrite=allow_overwrite,
        )
    try:
        # Flush to check for unique violations (due to attempting to replace beliefs)
        db.session.flush()
    except IntegrityError as e:
        current_app.logger.warning(e)
        db.session.rollback()

        # Catch only unique violations
        if not isinstance(e.orig, UniqueViolation):
            # reraise
            raise e.orig

        # Allow data to be replaced only in play mode
        if current_app.config.get("FLEXMEASURES_MODE", "") == "play":
            status = save_to_db(
                data=data,
                save_changed_beliefs_only=save_changed_beliefs_only,
                allow_overwrite=True,
            )
        else:
            # some beliefs represented replacements, which was forbidden
            status = "failed_due_to_forbidden_replacements"

    return status
