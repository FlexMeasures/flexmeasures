from datetime import datetime
import time

import pytz
from flask import request, current_app
from flask_json import as_json
from sqlalchemy import exc as sqla_exc

from flexmeasures.data.config import db
from flexmeasures.data.models.task_runs import LatestTaskRun
from flexmeasures.data.auth_setup import UNAUTH_STATUS_CODE, FORBIDDEN_STATUS_CODE


@as_json
def ping():
    return dict(message="ok"), 200


@as_json
def get_task_run():
    """
    Get latest task runs.
    This endpoint returns output conforming to the task monitoring tool (bobbydams/py-pinger)
    """
    task_name: str = request.args.get("name", "")

    def make_response(status: str, reason: str, last_run: datetime) -> dict:
        return dict(
            status=status,
            reason=reason,
            lastrun=last_run,
            frequency=current_app.config.get(
                "MONITOR_FREQUENCY_%s" % task_name.upper(), 10
            ),
            process="FlexMeasures",
            server=current_app.config.get("FLEXMEASURES_MODE", ""),
        )

    # check auth token
    token_name = current_app.config.get("SECURITY_TOKEN_AUTHENTICATION_HEADER")
    token = current_app.config.get("FLEXMEASURES_TASK_CHECK_AUTH_TOKEN", "")
    if token_name not in request.headers:
        return (
            make_response(
                "ERROR", "Not authenticated to check task status.", datetime(1970, 1, 1)
            ),
            UNAUTH_STATUS_CODE,
        )
    if request.headers.get(token_name) != token:
        return (
            make_response(
                "ERROR", "Not authorized to check task status.", datetime(1970, 1, 1)
            ),
            FORBIDDEN_STATUS_CODE,
        )

    if task_name is None or task_name == "":
        return make_response("ERROR", "No task name given.", datetime(1970, 1, 1)), 400

    try:
        last_known_run = LatestTaskRun.query.filter(
            LatestTaskRun.name == task_name
        ).first()
    except (sqla_exc.ResourceClosedError, sqla_exc.DatabaseError):
        # This is an attempt to make this more stable against some rare condition we encounter. Let's try once more.
        time.sleep(2)
        last_known_run = LatestTaskRun.query.filter(
            LatestTaskRun.name == task_name
        ).first()

    if not last_known_run:
        return (
            make_response(
                "ERROR",
                "Task %s has no last run time." % task_name,
                datetime(1970, 1, 1),
            ),
            404,
        )

    last_status = "OK" if last_known_run.status else "ERROR"
    return make_response(last_status, "", last_known_run.datetime), 200


@as_json
def post_task_run():
    """
    Post that a task has been (attempted to) run.
    Form fields to send in: name: str, status: bool [defaults to True], datetime: datetime [defaults to now]
    """
    task_name = request.form.get("name", "")
    if task_name == "":
        return {"status": "ERROR", "reason": "No task name given."}, 400
    date_time = request.form.get("datetime", datetime.utcnow().replace(tzinfo=pytz.utc))
    status = request.form.get("status", "True") == "True"
    try:
        task_run = LatestTaskRun.query.filter(
            LatestTaskRun.name == task_name
        ).one_or_none()
        if task_run is None:
            task_run = LatestTaskRun(name=task_name)
            db.session.add(task_run)
        task_run.datetime = date_time
        task_run.status = status
    except Exception as e:
        return {"status": "ERROR", "reason": str(e)}, 500
    return {"status": "OK"}, 200
