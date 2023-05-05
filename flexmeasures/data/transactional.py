"""
These, and only these, functions should help you with treating your own code
in the context of one database transaction. Which makes our lives easier.
"""
from __future__ import annotations

import sys

import click
from flask import current_app
from flask_sqlalchemy import SQLAlchemy

from flexmeasures.data import db
from flexmeasures.utils.error_utils import get_err_source_info
from flexmeasures.utils.coding_utils import optional_arg_decorator
from flexmeasures.data.models.task_runs import LatestTaskRun


def as_transaction(db_function):
    """Decorator for handling any function which contains SQLAlchemy commands as one database transaction (ACID).
    Calls db operation function and when it is done, commits the db session.
    Rolls back the session if anything goes wrong.
    If useful, the first argument can be the db (SQLAlchemy) object and the rest of the args
    are sent through to the function. If this happened, the session is closed at the end.
    """

    def wrap(*args, **kwargs):
        close_session = False
        # negotiate which db object to use
        db_obj_passed = len(args) > 0 and isinstance(args[0], SQLAlchemy)
        if db_obj_passed:
            the_db = args[0]
            close_session = True
        else:
            the_db = db
        # run actual function, handle any exceptions and re-raise
        try:
            db_function(*args, **kwargs)
            the_db.session.commit()
        except Exception as e:
            current_app.logger.error(
                "[%s] Encountered Problem: %s" % (db_function.__name__, str(e))
            )
            the_db.session.rollback()
            raise
        finally:
            if close_session:
                the_db.session.close()

    return wrap


def after_request_exception_rollback_session(exception):
    """
    Central place to handle transactions finally.
    So - usually your view code should not have to deal with
    rolling back.
    Our policy *is* that we don't auto-commit (we used to do that here).
    Some more reading is e.g. here https://github.com/pallets/flask-sqlalchemy/issues/216

    Register this on your app via the teardown_request setup method.
    We roll back the session if there was any error (which only has an effect if
    the session has not yet been committed).

    Flask-SQLAlchemy is closing the scoped sessions automatically."""
    if exception is not None:
        db.session.rollback()
        return


class PartialTaskCompletionException(Exception):
    """By raising this Exception in a task, no rollback will happen even if not everything was successful
    and the data which was generated will get committed. The task status will still be False, so the non-successful
    parts can be inspected."""

    pass


@optional_arg_decorator
def task_with_status_report(task_function, task_name: str | None = None):
    """Decorator for tasks which should report their runtime and status in the db (as LatestTaskRun entries).
    Tasks decorated with this endpoint should also leave committing or rolling back the session to this
    decorator (for the reasons that it is nice to centralise that but also practically, this decorator
    still needs to add to the session).
    If the task wants to commit partial results, and at the same time report that some things did not run well,
    it can raise a PartialTaskCompletionException and we recommend to use save-points (db.session.being_nested) to
    do partial rollbacks (see https://docs.sqlalchemy.org/en/latest/orm/session_transaction.html#using-savepoint)."""

    task_name_to_report = (
        task_name  # store this closure var somewhere else before we might assign to it
    )
    if task_name_to_report is None:
        task_name_to_report = task_function.__name__

    def wrap(*args, **kwargs):
        status: bool = True
        partial: bool = False
        try:
            task_function(*args, **kwargs)
            click.echo("[FLEXMEASURES] Task %s ran fine." % task_name_to_report)
        except Exception as e:
            exc_info = sys.exc_info()
            last_traceback = exc_info[2]
            click.echo(
                '[FLEXMEASURES] Task %s encountered a problem: "%s". More details: %s'
                % (task_name_to_report, str(e), get_err_source_info(last_traceback))
            )
            status = False
            if e.__class__ == PartialTaskCompletionException:
                partial = True
        finally:
            # make sure we roll back if there is no reason to commit
            if not (status is True or partial is True):
                db.session.rollback()

            # now save the status of the task
            db.session.begin_nested()  # any failure here does not invalidate any task results we might commit
            try:
                LatestTaskRun.record_run(task_name_to_report, status)
                click.echo(
                    "[FLEXMEASURES] Reported task %s status as %s"
                    % (task_name_to_report, status)
                )
                db.session.commit()
            except Exception as e:
                click.echo(
                    "[FLEXMEASURES] Could not report the running of task %s. Encountered the following problem: [%s]."
                    " The task might have run fine." % (task_name_to_report, str(e))
                )
                db.session.rollback()

        # now the final commit
        db.session.commit()
        db.session.remove()

    return wrap
