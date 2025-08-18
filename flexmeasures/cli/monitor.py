"""
CLI commands for monitoring functionality.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import click
from flask import current_app as app
from flask.cli import with_appcontext
from flask_mail import Message
from sentry_sdk import (
    capture_message as capture_message_for_sentry,
    set_context as set_sentry_context,
)
from sqlalchemy import select
from tabulate import tabulate

from flexmeasures.data import db
from flexmeasures.data.models.task_runs import LatestTaskRun
from flexmeasures.data.models.user import User
from flexmeasures.utils.time_utils import server_now
from flexmeasures.cli.utils import MsgStyle


@click.group("monitor")
def fm_monitor():
    """FlexMeasures: Monitor tasks."""


def send_task_monitoring_alert(
    task_name: str,
    msg: str,
    latest_run: LatestTaskRun | None = None,
    custom_msg: str | None = None,
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

    custom_msg_txt = ""
    if custom_msg:
        custom_msg_txt = f"\n\nNote: {custom_msg}"

    capture_message_for_sentry(msg)

    email_recipients = app.config.get("FLEXMEASURES_MONITORING_MAIL_RECIPIENTS", [])
    if len(email_recipients) > 0:
        email = Message(subject=f"Problem with task {task_name}", bcc=email_recipients)
        email.body = (
            f"{msg}\n\n{latest_run_txt}\nWe suggest to check the logs.{custom_msg_txt}"
        )
        app.mail.send(email)

    app.logger.error(f"{msg} {latest_run_txt} NOTE: {custom_msg}")


@fm_monitor.command("latest-run")
@with_appcontext
@click.option(
    "--task",
    type=(str, int),
    multiple=True,
    required=True,
    help="The name of the task and the maximal allowed minutes between successful runs. Use multiple times if needed.",
)
@click.option(
    "--custom-message",
    type=str,
    default="",
    help="Add this message to the monitoring alert (if one is sent).",
)
def monitor_latest_run(task, custom_message):
    """
    Check if the given task's last successful execution happened less than the allowed time ago.

    Tasks are CLI commands with the @task_with_status_report decorator.
    If not, alert someone, via email or sentry.
    """
    for t in task:
        task_name = t[0]
        app.logger.info(f"Checking latest run of task {task_name} ...")
        latest_run: LatestTaskRun = db.session.get(LatestTaskRun, task_name)
        if latest_run is None:
            msg = f"Task {task_name} has no last run and thus cannot be monitored. Is it configured properly?"
            send_task_monitoring_alert(task_name, msg, custom_msg=custom_message)
            raise click.Abort()

        now = server_now()
        acceptable_interval = timedelta(minutes=t[1])
        # check if latest run was recently enough
        if latest_run.datetime >= now - acceptable_interval:
            # latest run time is okay, let's check the status
            if latest_run.status is False:
                msg = f"A failure has been reported on task {task_name}."
                send_task_monitoring_alert(
                    task_name, msg, latest_run=latest_run, custom_msg=custom_message
                )
        else:
            msg = (
                f"Task {task_name}'s latest run time is outside of the acceptable range"
                f" ({acceptable_interval})."
            )
            send_task_monitoring_alert(
                task_name, msg, latest_run=latest_run, custom_msg=custom_message
            )
    app.logger.info("Done checking task runs ...")


def send_lastseen_monitoring_alert(
    users: list[User],
    last_seen_delta: timedelta,
    alerted_users: bool,
    account_role: str | None = None,
    user_role: str | None = None,
    txt_about_already_alerted_users: str = "",
):
    """
    Tell monitoring recipients and Sentry about user(s) we haven't seen in a while.
    """

    user_info = [
        [user.username, user.last_seen_at.strftime("%d %b %Y %I:%M:%S %p")]
        for user in users
    ]

    msg = (
        f"The following user(s) have not contacted this FlexMeasures server for more"
        f" than {last_seen_delta}, even though we expect they would have:\n\n"
    )

    msg += tabulate(user_info, headers=["User", "Last contact"])

    # Sentry
    set_sentry_context(
        "last_seen_context",
        {
            "delta": last_seen_delta,
            "alerted_users": alerted_users,
            "account_role": account_role,
            "user_role": user_role,
        },
    )
    capture_message_for_sentry(msg)

    # Email
    msg += "\n"
    if account_role:
        msg += f"\nThis alert concerns users whose accounts have the role '{account_role}'."
    if user_role:
        msg += f"\nThis alert concerns users who have the role '{user_role}'."
    if txt_about_already_alerted_users:
        msg += f"\n{txt_about_already_alerted_users}"
    if alerted_users:
        msg += "\n\nThe user(s) has/have been notified by email, as well."
    else:
        msg += (
            "\n\nThe user(s) has/have not been notified (--alert-users was not used)."
        )
    email_recipients = app.config.get("FLEXMEASURES_MONITORING_MAIL_RECIPIENTS", [])
    if len(email_recipients) > 0:
        email = Message(
            subject="Last contact by user(s) too long ago", bcc=email_recipients
        )
        email.body = msg
        app.mail.send(email)

    app.logger.error(msg)


@fm_monitor.command("last-seen")
@with_appcontext
@click.option(
    "--maximum-minutes-since-last-seen",
    type=int,
    required=True,
    help="Maximal number of minutes since last request.",
)
@click.option(
    "--alert-users/--do-not-alert-users",
    type=bool,
    default=False,
    help="If True, also send an email to the user. Defaults to False, as these users are often bots.",
)
@click.option(
    "--account-role",
    type=str,
    help="The name of an account role to filter for.",
)
@click.option(
    "--user-role",
    type=str,
    help="The name of a user role to filter for.",
)
@click.option(
    "--custom-user-message",
    type=str,
    default="",
    help="Add this message to the monitoring alert email to users (if one is sent).",
)
@click.option(
    "--only-newly-absent-users/--all-absent-users",
    type=bool,
    default=True,
    help="If True, a user is only included in this alert once after they were absent for too long. Defaults to True, so as to keep regular emails to low volume with newsworthy alerts.",
)
@click.option(
    "--task-name",
    type=str,
    default="monitor-last-seen-users",
    help="Optional name of the task, to distinguish finding out when the last monitoring happened (see --only-newly-absent-users).",
)
def monitor_last_seen(
    maximum_minutes_since_last_seen: int,
    alert_users: bool = False,
    account_role: str | None = None,
    user_role: str | None = None,
    custom_user_message: str | None = None,
    only_newly_absent_users: bool = True,
    task_name: str = "monitor-last-seen-users",
):
    """
    Check if given users last contact (via a request) happened less than the allowed time ago.

    Helpful for user accounts that are expected to contact FlexMeasures regularly (in an automated fashion).
    If the last contact was too long ago, we send alerts via Sentry, as well as emails to monitoring mail recipients.
    The user can be informed, as well.

    The set of users can be narrowed down by roles.

    Per default, this function will only alert you once per absent user (to avoid information overload).
    To (still) keep an overview over all absentees, we recommend to run this command in short regular intervals as-is
    and with --all-absent-users once per longer interval (e.g. per 24h).

    If you run distinct filters, you can use distinct task names, so the --only-newly-absent-users feature
    will work for all filters independently.
    """
    last_seen_delta = timedelta(minutes=maximum_minutes_since_last_seen)
    latest_run: LatestTaskRun = db.session.get(LatestTaskRun, task_name)

    # find users we haven't seen in the given time window (last_seen_at is naive UTC)
    users: list[User] = db.session.scalars(
        select(User).filter(
            User.last_seen_at < datetime.now(timezone.utc) - last_seen_delta
        )
    ).all()
    # role filters
    if account_role is not None:
        users = [user for user in users if user.account.has_role(account_role)]
    if user_role is not None:
        users = [user for user in users if user.has_role(user_role)]
    # filter out users who we already included in this check's last run
    txt_about_already_alerted_users = ""
    if only_newly_absent_users and latest_run:
        original_length = len(users)
        users = [
            user
            for user in users
            if user.last_seen_at.replace(tzinfo=timezone.utc) + last_seen_delta
            > latest_run.datetime
        ]
        if len(users) < original_length:
            txt_about_already_alerted_users = "There are (also) users who have been absent long, but one of the earlier monitoring runs already included them (run monitoring with --include-all-users-each-run to see them)."
    if not users:
        click.secho(
            f"All good ― no users were found with relevant criteria and last_seen_at longer than {maximum_minutes_since_last_seen} minutes ago. {txt_about_already_alerted_users}",
            **MsgStyle.SUCCESS,
        )
        raise click.Abort()

    # inform users & monitoring recipients
    if alert_users:
        for user in users:
            msg = (
                f"We noticed that user {user.username} has not been in contact with this FlexMeasures server"
                f" for at least {maximum_minutes_since_last_seen} minutes (last contact was {user.last_seen_at})."
            )
            if custom_user_message:
                msg += f"\n\n{custom_user_message}"
            else:
                msg += (
                    "\nBy our own accounting, this should usually not happen."
                    "\n\nMaybe you want to check if your local code is still working well."
                )
            email = Message(
                subject=f"Last contact by user {user.username} has been too long ago",
                recipients=[user.email],
            )
            email.body = msg
            app.mail.send(email)
    else:
        click.secho("Users are not being alerted.", **MsgStyle.ERROR)

    send_lastseen_monitoring_alert(
        users,
        last_seen_delta,
        alerted_users=alert_users,
        account_role=account_role,
        user_role=user_role,
        txt_about_already_alerted_users=txt_about_already_alerted_users,
    )

    # remember that we checked at this time
    LatestTaskRun.record_run(task_name, True)
    db.session.commit()


app.cli.add_command(fm_monitor)
