from flask_security import auth_token_required, roles_required

from bvp.api.common import bvp_api as bvp_api_ops
from bvp.api.common import implementations as ops_impl


@bvp_api_ops.route("/ping", methods=["GET"])
def get_ping():
    return ops_impl.ping()


@bvp_api_ops.route("/getLatestTaskRun", methods=["GET"])
def get_task_run():
    return ops_impl.get_task_run()


@bvp_api_ops.route("/postLatestTaskRun", methods=["POST"])
@auth_token_required
@roles_required("task-runner")
def post_task_run():
    return ops_impl.post_task_run()
