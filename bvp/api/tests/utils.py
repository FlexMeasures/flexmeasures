import json

from flask import url_for

"""
Useful things for API testing
"""


def get_auth_token(client, user_email, password):
    """
    Get an auth token for a user
    """
    print("Getting auth token for %s ..." % user_email)
    auth_data = json.dumps({"email": user_email, "password": password})
    auth_response = client.post(
        url_for("bvp_api.request_auth_token"),
        data=auth_data,
        headers={"content-type": "application/json"},
    )
    if "errors" in auth_response.json:
        raise Exception(";".join(auth_response.json["errors"]))
    return auth_response.json["auth_token"]


def get_task_run(client, task_name: str):
    """Utility for getting task run information"""
    return client.get(
        url_for("bvp_api.get_task_run"),
        query_string={"name": task_name},
        headers={
            "Authentication-Token": get_auth_token(
                client, "task_runner@seita.nl", "testtest"
            )
        },
    )


def post_task_run(client, task_name: str, status: bool = True):
    """Utility for getting task run information"""
    return client.post(
        url_for("bvp_api.post_task_run"),
        data={"name": task_name, "status": status},
        headers={
            "Authentication-Token": get_auth_token(
                client, "task_runner@seita.nl", "testtest"
            )
        },
    )
