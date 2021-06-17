from datetime import timedelta

import click
from flask import current_app as app
from flask.cli import with_appcontext
from flask_mail import Message
from sentry_sdk import capture_message as capture_message_for_sentry

from flexmeasures.data.models.task_runs import LatestTaskRun
from flexmeasures.utils.time_utils import server_now


@click.group("monitor")
def fm_monitor():
    """FlexMeasures: Monitor tasks."""


def send_monitoring_alert(task_name: str, msg: str):
    """
    Send any monitoring message per Sentry and per email.
    """
    capture_message_for_sentry(msg)
    email_recipients = app.config.get("MAIL_MONITORING_RECIPIENTS", "").split(",")
    if len(email_recipients) > 0:
        email = Message(subject=f"Problem with task {task_name}", bcc=email_recipients)
        email.body = msg
        app.mail.send(email)


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
            msg = f"Task {task_name} has no last run. Is it configured properly?"
            app.logger.warning(msg)
            return
        now = server_now()
        acceptable_interval = timedelta(minutes=t[1])
        if (
            now - acceptable_interval
            <= latest_run.datetime
            <= now + acceptable_interval
        ):
            # last time is okay, let's check the status
            if latest_run.status is False:
                msg = f"Error: Failure reported on task {task_name} at {latest_run.datetime}."
                app.logger.error(msg)
                send_monitoring_alert(task_name, msg)
        else:
            msg = (
                f"Task {task_name} is outside of the acceptable {acceptable_interval}"
                f" minute range. Last run was {latest_run.datetime}"
            )
            app.logger.error(msg)
            send_monitoring_alert(task_name, msg)
    app.logger.info("Done checking task runs ...")


app.cli.add_command(fm_monitor)
