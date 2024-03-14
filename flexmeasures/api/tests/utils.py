from __future__ import annotations

import json

from flask import url_for, current_app, Response
from sqlalchemy import select

from flexmeasures.data import db
from flexmeasures.data.services.users import find_user_by_email
from flexmeasures.data.models.user import Account


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


class AccountContext(object):
    """
    Context manager for a temporary account instance from the DB,
    which is expunged from the session at Exit.
    Expunging is useful, so that the API call being tested still operates on
    a "fresh" session.
    While the context is alive, you can collect any useful information, like
    the account's assets:

    with AccountContext("Supplier") as supplier:
        assets = supplier.generic_assets
    """

    def __init__(self, account_name: str):
        self.the_account = db.session.execute(
            select(Account).filter(Account.name == account_name)
        ).scalar_one_or_none()

    def __enter__(self):
        return self.the_account

    def __exit__(self, type, value, traceback):
        db.session.expunge(self.the_account)


class UserContext(object):
    """
    Context manager for a temporary user instance from the DB,
    which is expunged from the session at Exit.
    Expunging is useful, so that the API call being tested still operates on
    a "fresh" session.
    While the context is alive, you can collect any useful information, like
    the user's assets:

    with UserContext("test_prosumer_user@seita.nl") as prosumer:
        user_roles = prosumer.roles
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


def check_deprecation(
    response: Response,
    deprecation: str | None = "Tue, 13 Dec 2022 23:59:59 GMT",
    sunset: str | None = "Tue, 31 Jan 2023 23:59:59 GMT",
):
    """Check deprecation and sunset headers.

    Also make sure we link to some url for further info.
    If deprecation is None, make sure there are *no* deprecation headers.
    If sunset is None, make sure there are *no* sunset headers.
    """
    print(response.headers)
    if deprecation:
        assert deprecation in response.headers.getlist("Deprecation")
        assert any(
            'rel="deprecation"' in link for link in response.headers.getlist("Link")
        )
    else:
        assert deprecation not in response.headers.getlist("Deprecation")
        assert all(
            'rel="deprecation"' not in link for link in response.headers.getlist("Link")
        )
    if sunset:
        assert sunset in response.headers.getlist("Sunset")
        assert any('rel="sunset"' in link for link in response.headers.getlist("Link"))
    else:
        assert sunset not in response.headers.getlist("Sunset")
        assert all(
            'rel="sunset"' not in link for link in response.headers.getlist("Link")
        )
