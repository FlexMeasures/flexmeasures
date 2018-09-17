import os
import sys
from datetime import datetime

import pytz
import click

from bvp.data.config import db
from bvp.utils.error_utils import get_err_source_info
from bvp.data.models.task_runs import LatestTaskRun


def install_secret_key(app, filename="secret_key"):
    """Configure the SECRET_KEY from a file
    in the instance directory.

    If the file does not exist, print instructions
    to create it from a shell with a random key,
    then exit.
    """
    filename = os.path.join(app.instance_path, filename)
    try:
        app.config["SECRET_KEY"] = open(filename, "rb").read()
    except IOError:
        print("Error: No secret key. Create it with:")
        if not os.path.isdir(os.path.dirname(filename)):
            print("mkdir -p", os.path.dirname(filename))
        print("head -c 24 /dev/urandom >", filename)
        sys.exit(2)


def task_with_status_report(task_function):
    """Decorator for tasks which should report their runtime and status in the db (as LatestTaskRun entries).
    Tasks decorated with this endpoint should also leave committing or rolling back the session to this
    decorator (for the reasons that it is nice to centralise that but also practically, this still needs to
    add to the session)."""

    def wrap(*args, **kwargs):
        status: bool = True
        try:
            task_function(*args, **kwargs)
            click.echo("[BVP] Task %s ran fine." % task_function.__name__)
        except Exception as e:
            exc_info = sys.exc_info()
            last_traceback = exc_info[2]
            click.echo(
                '[BVP] Task %s encountered a problem: "%s". More details: %s'
                % (task_function.__name__, str(e), get_err_source_info(last_traceback))
            )
            status = False
        finally:
            try:
                # take care of finishing the transaction correctly
                if status is True:
                    db.session.commit()
                else:
                    db.session.rollback()

                # now save the status of the task
                task_name = task_function.__name__
                task_run = LatestTaskRun.query.filter(
                    LatestTaskRun.name == task_name
                ).one_or_none()
                if task_run is None:
                    task_run = LatestTaskRun(name=task_name)
                    db.session.add(task_run)
                task_run.datetime = datetime.utcnow().replace(tzinfo=pytz.utc)
                task_run.status = status
                db.session.commit()

            except Exception as e:
                click.echo(
                    "[BVP] Could not report the running of Task %s, encountered the following problem: %s"
                    % (task_function.__name__, str(e))
                )

    return wrap
