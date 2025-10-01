from flask import current_app, stream_with_context, Response
from flask_security import auth_token_required
from werkzeug.exceptions import NotFound

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
@auth_token_required
@roles_required("debugger")
def stream_logs():
    """Stream server logs for debugging."""
    if current_app.config.get("LOGGING_LEVEL") != "DEBUG":
        raise NotFound

    def generate():
        with open("flexmeasures.log") as f:
            f.seek(0, 2)  # go to end of file
            while True:
                line = f.readline()
                if line:
                    yield line

    return Response(stream_with_context(generate()), mimetype="text/plain")
