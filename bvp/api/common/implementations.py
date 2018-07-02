from datetime import datetime

import pytz
from flask import request
from flask_json import as_json

from bvp.data.config import db
from bvp.data.models.task_runs import LatestTaskRun
# from bvp.api import ma

""""
class TaskSchema(ma.ModelSchema):
    class Meta:
        model = LatestTaskRun
        fields = ("datetime", "status")
        sqla_session = db.session
"""


@as_json
def ping():
    return dict(message="ok"), 200


@as_json
def get_task_run():
    """
    Get latest task runs
    """
    task_name = request.args.get("name")
    if task_name is None or task_name == "":
        return {"error": "No task name given."}, 400

    last_run = LatestTaskRun.query.filter(LatestTaskRun.name == task_name).first()
    if not last_run:
        return {"error": "Task %s has no last run time." % task_name}, 400
    # return TaskSchema().jsonify(last_run)
    return dict(datetime=last_run.datetime, status=last_run.status)


@as_json
def post_task_run():
    """
    Post that a task has been (attempted to) run.
    """
    task_name = request.form.get("name", "")
    if task_name == "":
        return {"error": "No task name given."}, 400
    date_time = request.form.get("datetime", datetime.utcnow().replace(tzinfo=pytz.utc))
    status = request.form.get("status", "True") == "True"
    task_run = LatestTaskRun.query.filter(LatestTaskRun.name == task_name).one_or_none()
    if task_run is None:
        task_run = LatestTaskRun(name=task_name)
        db.session.add(task_run)
    task_run.datetime = date_time
    task_run.status = status
    db.session.commit()  # TODO: should we strive to have only one commit per request?
    return {"message": "ok"}, 200
