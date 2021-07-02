from datetime import timedelta
from typing import Optional

import click
from flask import current_app as app
from flask.cli import with_appcontext
from flask_mail import Message
from sentry_sdk import (
    capture_message as capture_message_for_sentry,
    set_context as set_sentry_context,
)

from flexmeasures.data.models.task_runs import LatestTaskRun
from flexmeasures.utils.time_utils import server_now


@click.group("monitor")
def fm_monitor():
    """FlexMeasures: Monitor tasks."""


def send_monitoring_alert(
    task_name: str, msg: str, latest_run: Optional[LatestTaskRun] = None
):
    """
    Send any monitoring message per Sentry and per email. Also log an error.
    """
    latest_run_txt = ""
    if latest_run:
        set_sentry_context(
            "latest_run", {"time": latest_run.datetime, "status": latest_run.status}
        )
        latest_run_txt = (
            f"Last run was at {latest_run.datetime}, status was: {latest_run.status}"
        )

    capture_message_for_sentry(msg)

    email_recipients = app.config.get("FLEXMEASURES_MONITORING_MAIL_RECIPIENTS", [])
    if len(email_recipients) > 0:
        email = Message(subject=f"Problem with task {task_name}", bcc=email_recipients)
        email.body = f"{msg}\n\n{latest_run_txt}\nWe suggest to check the logs."
        app.mail.send(email)

    app.logger.error(f"{msg} {latest_run_txt}")


@fm_monitor.command("tasks")
@with_appcontext
@click.option(
    "--task",
    type=(str, int),
    multiple=True,
    required=True,
    help="The name of the task and the maximal allowed minutes between successful runs. Use multiple times if needed.",
)
def monitor_tasks(task):
    """
    Check if the given task's last successful execution happened less than the allowed time ago.
    If not, alert someone, via email or sentry.
    """
    for t in task:
        task_name = t[0]
        app.logger.info(f"Checking latest run of task {task_name} ...")
        latest_run: LatestTaskRun = LatestTaskRun.query.get(task_name)
        if latest_run is None:
            msg = f"Task {task_name} has no last run and thus cannot be monitored. Is it configured properly?"
            send_monitoring_alert(task_name, msg)
            return
        now = server_now()
        acceptable_interval = timedelta(minutes=t[1])
        # check if latest run was recently enough
        if latest_run.datetime >= now - acceptable_interval:
            # latest run time is okay, let's check the status
            if latest_run.status is False:
                msg = f"A failure has been reported on task {task_name}."
                send_monitoring_alert(task_name, msg, latest_run)
        else:
            msg = (
                f"Task {task_name}'s latest run time is outside of the acceptable range "
                f"({acceptable_interval})."
            )
            app.logger.error(msg)
            send_monitoring_alert(task_name, msg, latest_run)
    app.logger.info("Done checking task runs ...")


app.cli.add_command(fm_monitor)
