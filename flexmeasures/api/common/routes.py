from collections import deque
import os

from flask import current_app, request, Response
from flask_security import auth_token_required, login_required
from werkzeug.exceptions import NotFound, abort

from flexmeasures.auth.decorators import roles_required
from flexmeasures.api.common import flexmeasures_api as flexmeasures_api_ops
from flexmeasures.api.common import implementations as ops_impl


@flexmeasures_api_ops.route("/ping", methods=["GET"])
def get_ping():
    return ops_impl.ping()


@flexmeasures_api_ops.route("/getLatestTaskRun", methods=["GET"])
def get_task_run():
    return ops_impl.get_task_run()


@flexmeasures_api_ops.route("/postLatestTaskRun", methods=["POST"])
@auth_token_required
@roles_required("task-runner")
def post_task_run():
    return ops_impl.post_task_run()


@flexmeasures_api_ops.route("/logs")
@login_required
@roles_required("debugger")
def stream_logs():
    """Stream server logs for debugging."""
    if current_app.config.get("LOGGING_LEVEL") != "DEBUG":
        raise NotFound

    log_file = "flexmeasures.log"
    n = int(request.args.get("tail", 200))
    if not os.path.exists(log_file):
        abort(404, "Log file not found")
    with open(log_file, "r") as f:
        last_n_lines = deque(f, maxlen=n)
    return Response("".join(last_n_lines), mimetype="text/plain")
