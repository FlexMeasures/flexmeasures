import json

from flask import url_for, current_app

from flexmeasures.data.config import db
from flexmeasures.data.services.users import find_user_by_email

"""
Useful things for API testing
"""


def get_auth_token(client, user_email, password):
    """
    Get an auth token for a user via the API (like users need to do in real life).
    TODO: if you have the user object (e.g. from DB, you simply get the token via my_user.get_auth_token()!
    """
    print("Getting auth token for %s ..." % user_email)
    auth_data = json.dumps({"email": user_email, "password": password})
    auth_response = client.post(
        url_for("flexmeasures_api.request_auth_token"),
        data=auth_data,
        headers={"content-type": "application/json"},
    )
    if "errors" in auth_response.json:
        raise Exception(";".join(auth_response.json["errors"]))
    return auth_response.json["auth_token"]


class UserContext(object):
    """
    Context manager for a temporary user instance from the DB,
    which is expunged from the session at Exit.
    Expunging is useful, so that the API call being tested still operates on
    a "fresh" session.
    While the context is alive, you can collect any useful information, like
    the user's assets:

    with UserContext("test_prosumer@seita.nl") as prosumer:
        assets = prosumer.assets
    """

    def __init__(self, user_email: str):
        self.the_user = find_user_by_email(user_email)

    def __enter__(self):
        return self.the_user

    def __exit__(self, type, value, traceback):
        db.session.expunge(self.the_user)


def get_task_run(client, task_name: str, token=None):
    """Utility for getting task run information"""
    headers = {"Authorization": token}
    if token is None:
        headers["Authorization"] = current_app.config.get(
            "FLEXMEASURES_TASK_CHECK_AUTH_TOKEN", ""
        )
    elif token == "NOAUTH":
        headers = {}
    return client.get(
        url_for("flexmeasures_api_ops.get_task_run"),
        query_string={"name": task_name},
        headers=headers,
    )


def post_task_run(client, task_name: str, status: bool = True):
    """Utility for getting task run information"""
    return client.post(
        url_for("flexmeasures_api_ops.post_task_run"),
        data={"name": task_name, "status": status},
        headers={
            "Authorization": get_auth_token(client, "task_runner@seita.nl", "testtest")
        },
    )
