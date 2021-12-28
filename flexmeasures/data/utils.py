from typing import List, Optional, Union

import click
from flask import current_app
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
) -> Union[str, List[str]]:
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
    Replacing beliefs is not allowed, except on servers in play mode.

    :param data: BeliefsDataFrame (or a list thereof) to be saved
    :param save_changed_beliefs_only: if True, beliefs that are already stored in the database with an earlier belief time are dropped.
    :returns: status string (or a list thereof), one of the following:
              - 'success': all beliefs were saved
              - 'success_with_replacements': all beliefs were saves, (some) replacing pre-existing beliefs
              - 'success_but_data_empty': there was nothing to save
              - 'success_but_nothing_new': no beliefs represented a state change
              - 'success_but_partially_new': not all beliefs represented a state change
              - 'failed_due_to_forbidden_replacements': no beliefs were saved, because replacing pre-existing beliefs is forbidden
    """

    # Convert to list
    if not isinstance(data, list):
        timed_values_list = [data]
    else:
        timed_values_list = data

    success_list = []
    for timed_values in timed_values_list:

        if timed_values.empty:
            # Nothing to save
            success_list.append("success_but_data_empty")
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

            # Work around bug in which groupby still introduces an index level, even though we asked it not to
            if None in timed_values.index.names:
                timed_values.index = timed_values.index.droplevel(None)

            if timed_values.empty:
                # No state changes among the beliefs
                success_list.append("success_but_nothing_new")
                continue
        else:
            len_after = len_before

        # if timed_values.empty or (save_changed_beliefs_only and len_after < len_before):
        #     current_app.logger.info("Nothing new to save")
        #     success_list.append(False)  # no data or data already existed or data doesn't represent updated beliefs
        # else:
        current_app.logger.info("SAVING TO DB...")
        try:
            TimedBelief.add_to_session(
                session=db.session, beliefs_data_frame=timed_values
            )
            db.session.flush()
            db.session.commit()
            if len_after < len_before:
                # new data was saved
                success_list.append("success_but_partially_new")
            else:
                # all data was saved
                success_list.append("success")
        except IntegrityError as e:
            current_app.logger.warning(e)
            db.session.rollback()

            # Allow data to be replaced only in play mode
            if current_app.config.get("FLEXMEASURES_MODE", "") == "play":
                TimedBelief.add_to_session(
                    session=db.session,
                    beliefs_data_frame=timed_values,
                    allow_overwrite=True,
                )
                db.session.commit()
                # some beliefs have been replaced, which was allowed
                success_list.append("success_with_replacements")
            else:
                # some beliefs represented replacements, which was forbidden
                success_list.append("failed_due_to_forbidden_replacements")

    # Return a success indicator for each BeliefsDataFrame
    if not isinstance(data, list):
        return success_list[0]
    return success_list
