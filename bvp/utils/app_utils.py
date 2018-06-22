import os
import sys
from datetime import datetime

import pytz
from flask import Flask
import click


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
    """Decorator for tasks which should report their runtime and status."""

    def wrap(app: Flask, *args, **kwargs):
        status: bool = True
        try:
            task_function(app, *args, **kwargs)
            click.echo("Task %s ran fine." % task_function.__name__)
        except Exception as e:
            click.echo(
                "Task %s encountered a problem: %s" % (task_function.__name__, str(e))
            )
            status = False
        finally:
            try:
                from bvp.data.models.task_runs import LatestTaskRun

                task_name = task_function.__name__
                task_run = LatestTaskRun.query.filter(
                    LatestTaskRun.name == task_name
                ).one_or_none()
                if task_run is None:
                    task_run = LatestTaskRun(name=task_name)
                    app.db.session.add(task_run)
                task_run.datetime = datetime.utcnow().replace(tzinfo=pytz.utc)
                task_run.status = status
                app.db.session.commit()
            except Exception as e:
                click.echo(
                    "Could not report the running of Task %s, encountered the following problem: %s"
                    % (task_function.__name__, str(e))
                )

    return wrap
