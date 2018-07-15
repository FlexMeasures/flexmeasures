import copy
import json
from typing import List

from flask import url_for

from bvp.api.common.utils.api_utils import parse_as_list, parse_entity_address
from bvp.data.models.assets import Asset

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
        url_for("bvp_api_ops.get_task_run"),
        query_string={"name": task_name},
        headers={
            "Authorization": get_auth_token(client, "task_runner@seita.nl", "testtest")
        },
    )


def post_task_run(client, task_name: str, status: bool = True):
    """Utility for getting task run information"""
    return client.post(
        url_for("bvp_api_ops.post_task_run"),
        data={"name": task_name, "status": status},
        headers={
            "Authorization": get_auth_token(client, "task_runner@seita.nl", "testtest")
        },
    )


def message_replace_name_with_ea(message_with_connections_as_asset_names: dict) -> dict:
    """For each connection in the message specified by a name, replace that name with the correct entity address."""
    message_with_connections_as_eas = copy.deepcopy(
        message_with_connections_as_asset_names
    )
    if "connection" in message_with_connections_as_asset_names:
        message_with_connections_as_eas["connection"] = asset_replace_name_with_id(
            parse_as_list(message_with_connections_as_eas["connection"])
        )
    elif "connections" in message_with_connections_as_asset_names:
        message_with_connections_as_eas["connections"] = asset_replace_name_with_id(
            parse_as_list(message_with_connections_as_eas["connections"])
        )
    elif "groups" in message_with_connections_as_asset_names:
        for i, group in enumerate(message_with_connections_as_asset_names["groups"]):
            if "connection" in group:
                message_with_connections_as_eas["groups"][i][
                    "connection"
                ] = asset_replace_name_with_id(parse_as_list(group["connection"]))
            elif "connections" in group:
                message_with_connections_as_eas["groups"][i][
                    "connections"
                ] = asset_replace_name_with_id(parse_as_list(group["connections"]))
    return message_with_connections_as_eas


def asset_replace_name_with_id(connections_as_name: List[str]) -> List[str]:
    """Look up the owner and id given the asset name and constructs a type 1 USEF entity address."""
    connections_as_ea = copy.deepcopy(connections_as_name)
    for i, connection in enumerate(connections_as_name):
        scheme_and_naming_authority, owner_id, asset_name = parse_entity_address(
            connection
        )
        asset = Asset.query.filter(Asset.name == asset_name).one_or_none()
        asset_id = asset.id
        owner_id = asset.owner_id
        scheme_and_naming_authority = "ea1.2018-06.com.a1-bvp.api"
        connections_as_ea[i] = "%s:%s:%s" % (
            scheme_and_naming_authority,
            owner_id,
            asset_id,
        )
    return connections_as_ea
