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
from sqlalchemy import exc as sqla_exc, select
from tabulate import tabulate

from flexmeasures.data import db
from flexmeasures.data.models.task_runs import LatestTaskRun
from flexmeasures.data.models.user import Account, User
from flexmeasures.data.schemas.account import AccountIdField
from flexmeasures.utils.time_utils import server_now
from flexmeasures.cli.utils import MsgStyle


@click.group("monitor")
def fm_monitor():
    """FlexMeasures: Monitor tasks."""


def get_default_monitoring_email_recipients():
    recipients = app.config.get("FLEXMEASURES_DEFAULT_MONITORING_MAIL_RECIPIENTS", [])
    deprecated_recipients = app.config.get("FLEXMEASURES_MONITORING_MAIL_RECIPIENTS")
    if deprecated_recipients:
        app.logger.warning(
            "FLEXMEASURES_MONITORING_MAIL_RECIPIENTS is deprecated. Use "
            "FLEXMEASURES_DEFAULT_MONITORING_MAIL_RECIPIENTS instead."
        )
        if not recipients:
            recipients = deprecated_recipients
    if isinstance(recipients, str):
        recipients = [recipients]
    return recipients


def get_monitoring_email_recipients(
    informed_users: tuple[str | int, ...] = ()
) -> list[str]:
    if not informed_users:
        return get_default_monitoring_email_recipients()

    recipients = []
    for user_identifier in informed_users:
        user_identifier = str(user_identifier)
        if user_identifier.isdecimal():
            user = db.session.get(User, int(user_identifier))
        else:
            user = db.session.execute(
                select(User).filter_by(email=user_identifier)
            ).scalar_one_or_none()
        if user is None:
            raise click.BadParameter(
                f"No user with ID or email address {user_identifier} exists.",
                param_hint="--inform-this-user",
            )
        recipients.append(user.email)
    return recipients


def send_task_monitoring_alert(
    task_name: str,
    msg: str,
    latest_run: LatestTaskRun | None = None,
    custom_msg: str | None = None,
    email_recipients: list[str] | None = None,
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

    if email_recipients is None:
        email_recipients = get_default_monitoring_email_recipients()
    if len(email_recipients) > 0:
        app.logger.debug(
            f"Monitoring alert about latest task run of {task_name}, send to {email_recipients}"
        )
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
@click.option(
    "--inform-this-user",
    type=str,
    multiple=True,
    help="User ID or email address to send the monitoring alert to. Use multiple times if needed. If not used, the default monitoring mail recipients are informed.",
)
def monitor_latest_run(task, custom_message, inform_this_user: tuple[str, ...] = ()):
    """
    Check if the given task's last successful execution happened less than the allowed time ago.

    Tasks are CLI commands with the @task_with_status_report decorator.
    If not, alert someone, via email or sentry.
    """
    email_recipients = get_monitoring_email_recipients(inform_this_user)
    for t in task:
        task_name = t[0]
        app.logger.info(f"Checking latest run of task {task_name} ...")
        try:
            latest_run: LatestTaskRun = db.session.get(LatestTaskRun, task_name)
        except (sqla_exc.ResourceClosedError, sqla_exc.DatabaseError):
            msg = f"Task {task_name} could not be checked due to a database connectivity problem."
            send_task_monitoring_alert(
                task_name,
                msg,
                custom_msg=custom_message,
                email_recipients=email_recipients,
            )
            raise click.Abort()
        if latest_run is None:
            msg = f"Task {task_name} has no last run and thus cannot be monitored. Is it configured properly?"
            send_task_monitoring_alert(
                task_name,
                msg,
                custom_msg=custom_message,
                email_recipients=email_recipients,
            )
            raise click.Abort()

        now = server_now()
        acceptable_interval = timedelta(minutes=t[1])
        # check if latest run was recently enough
        if latest_run.datetime >= now - acceptable_interval:
            # latest run time is okay, let's check the status
            if latest_run.status is False:
                msg = f"A failure has been reported on task {task_name}."
                send_task_monitoring_alert(
                    task_name,
                    msg,
                    latest_run=latest_run,
                    custom_msg=custom_message,
                    email_recipients=email_recipients,
                )
        else:
            msg = (
                f"Task {task_name}'s latest run time is outside of the acceptable range"
                f" ({acceptable_interval})."
            )
            send_task_monitoring_alert(
                task_name,
                msg,
                latest_run=latest_run,
                custom_msg=custom_message,
                email_recipients=email_recipients,
            )
    app.logger.info("Done checking task runs ...")


def send_lastseen_monitoring_alert(
    users: list[User],
    last_seen_delta: timedelta,
    alerted_users: bool,
    account_ids: list[int] | None = None,
    client_account_ids: list[int] | None = None,
    consultant_account_id: int | None = None,
    account_role: str | None = None,
    user_role: str | None = None,
    txt_about_already_alerted_users: str = "",
    email_recipients: list[str] | None = None,
):
    """
    Tell monitoring recipients and Sentry about user(s) we haven't seen in a while.
    """

    user_info = [
        [
            user.username,
            user.id,
            user.account_id,
            user.last_seen_at.strftime("%d %b %Y %I:%M:%S %p"),
        ]
        for user in users
    ]

    msg = (
        f"The following user(s) have not contacted this FlexMeasures server for more"
        f" than {last_seen_delta}, even though we expect they would have:\n\n"
    )

    msg += tabulate(
        user_info, headers=["User", "User ID", "Account ID", "Last contact"]
    )

    # Sentry
    set_sentry_context(
        "last_seen_context",
        {
            "delta": last_seen_delta,
            "alerted_users": alerted_users,
            "account_ids": account_ids,
            "client_account_ids": client_account_ids,
            "consultant_account_id": consultant_account_id,
            "account_role": account_role,
            "user_role": user_role,
        },
    )
    capture_message_for_sentry(msg)

    # Email
    msg += "\n"
    if account_ids:
        if len(account_ids) == 1:
            msg += f"\nThis alert concerns users whose account has ID {account_ids[0]}."
        else:
            account_ids_txt = ", ".join(str(account_id) for account_id in account_ids)
            msg += f"\nThis alert concerns users whose accounts have IDs {account_ids_txt}."
    if consultant_account_id:
        msg += (
            "\nThis alert concerns users whose accounts are clients of consultant "
            f"account {consultant_account_id}"
        )
        if client_account_ids:
            client_account_ids_txt = ", ".join(
                str(account_id) for account_id in client_account_ids
            )
            msg += f" ({client_account_ids_txt})."
        else:
            msg += "."
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
    if email_recipients is None:
        email_recipients = get_default_monitoring_email_recipients()
    if len(email_recipients) > 0:
        email = Message(
            subject="Last contact by user(s) too long ago", bcc=email_recipients
        )
        email.body = msg
        app.mail.send(email)
    app.logger.debug(
        f"Monitoring alert about users not seen in a while, send to {email_recipients}"
    )

    app.logger.error(msg)


def get_absent_users(
    last_seen_delta: timedelta,
    account_ids: list[int],
    client_account_ids: list[int],
    filter_by_client_accounts: bool,
    account_role: str | None = None,
    user_role: str | None = None,
) -> list[User]:
    """
    Get users whose last contact is too old, narrowed down by account and role filters.
    """
    query = select(User).filter(
        User.last_seen_at < datetime.now(timezone.utc) - last_seen_delta
    )
    if account_ids:
        query = query.filter(User.account_id.in_(account_ids))
    if filter_by_client_accounts:
        query = query.filter(User.account_id.in_(client_account_ids))
    query = query.order_by(User.last_seen_at.asc())
    users = db.session.scalars(query).all()

    if account_role is not None:
        users = [user for user in users if user.account.has_role(account_role)]
    if user_role is not None:
        users = [user for user in users if user.has_role(user_role)]
    return users


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
    "--account",
    "accounts",
    required=False,
    type=AccountIdField(),
    multiple=True,
    help="The ID of an account to filter for. Use multiple times if needed.",
)
@click.option(
    "--consultancy",
    type=AccountIdField(),
    help="The ID of a consultant account whose client accounts should be monitored.",
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
    help="If True, a user is only included in this alert once after they were absent for too long. Defaults to True, so as to keep regular emails to low volume with newsworthy alerts. See also --task-name.",
)
@click.option(
    "--task-name",
    type=str,
    default="monitor-last-seen-users",
    help="Optional name of the task, to distinguish finding out when the last monitoring happened (see --only-newly-absent-users). Helps to distinguish multiple versions of this command.",
)
@click.option(
    "--inform-this-user",
    type=str,
    multiple=True,
    help="User ID or email address to send the monitoring alert to. Use multiple times if needed. If not used, the default monitoring mail recipients are informed.",
)
def monitor_last_seen(
    maximum_minutes_since_last_seen: int,
    alert_users: bool = False,
    account_role: str | None = None,
    accounts: tuple[Account, ...] = (),
    consultancy: Account | None = None,
    user_role: str | None = None,
    custom_user_message: str | None = None,
    only_newly_absent_users: bool = True,
    task_name: str = "monitor-last-seen-users",
    inform_this_user: tuple[str, ...] = (),
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
    latest_run: LatestTaskRun | None = None
    users: list[User] = []
    app.logger.debug(
        f"Checking which users have not been seen for more than {last_seen_delta} ..."
    )
    email_recipients = get_monitoring_email_recipients(inform_this_user)
    account_ids = [account.id for account in accounts]
    client_account_ids = (
        [account.id for account in consultancy.get_all_client_accounts()]
        if consultancy is not None
        else []
    )

    try:
        latest_run: LatestTaskRun = db.session.get(LatestTaskRun, task_name)
        users = get_absent_users(
            last_seen_delta,
            account_ids,
            client_account_ids,
            consultancy is not None,
            account_role,
            user_role,
        )
    except (sqla_exc.ResourceClosedError, sqla_exc.DatabaseError):
        if len(email_recipients) > 0:
            email = Message(
                subject="Could not monitor last seen status of users",
                bcc=email_recipients,
            )
            email.body = "Due to a database connectivity problem, we could not check which users have not been seen in a while.\nWe suggest to check the logs."
            app.mail.send(email)
        raise click.Abort()

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
            txt_about_already_alerted_users = "There are (also) users who have been absent long, but one of the earlier monitoring runs already included them (run monitoring with --all-absent-users to see them)."
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
        account_ids=account_ids,
        client_account_ids=client_account_ids,
        consultant_account_id=consultancy.id if consultancy else None,
        account_role=account_role,
        user_role=user_role,
        txt_about_already_alerted_users=txt_about_already_alerted_users,
        email_recipients=email_recipients,
    )

    # remember that we checked at this time
    LatestTaskRun.record_run(task_name, True)
    db.session.commit()


app.cli.add_command(fm_monitor)
