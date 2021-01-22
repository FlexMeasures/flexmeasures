from flask_security import auth_token_required, roles_required

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
