from typing import List

from bvp.api.common.utils.api_utils import parse_as_list, parse_entity_address
from bvp.data.models.assets import Asset


def message_for_get_meter_data(no_connection: bool = False, invalid_unit: bool = False, no_unit: bool = False) -> dict:
    message = {
        "type": "GetMeterDataRequest",
        "start": "2015-01-01T00:00:00Z",
        "duration": "PT1H30M",
        "connection": "CS 1",
        "unit": "MW",
    }
    if no_connection:
        message.pop("connection", None)
    if no_unit:
        message.pop("unit", None)
    elif invalid_unit:
        message["unit"] = "MW/h"
    return message


def message_for_post_meter_data(no_connection: bool = False,
                                single_connection: bool = False,
                                single_connection_group: bool = False) -> dict:
    message = {
        "type": "PostMeterDataRequest",
        "groups": [
            {
                "connections": ["CS 1", "CS 2"],
                "values": [306.66, 306.66, 0, 0, 306.66, 306.66],
            },
            {"connection": ["CS 3"], "values": [306.66, 0, 0, 0, 306.66, 306.66]},
        ],
        "start": "2015-01-01T00:00:00Z",
        "duration": "PT1H30M",
        "unit": "MW",
    }
    if no_connection:
        message.pop("groups", None)
    elif single_connection:
        message["connection"] = message["groups"][0]["connections"][0]
        message["values"] = message["groups"][1]["values"]
        message.pop("groups", None)
    elif single_connection_group:
        message["connections"] = message["groups"][0]["connections"]
        message["values"] = message["groups"][0]["values"]
        message.pop("groups", None)

    return message


def message_replace_name_with_ea(message_with_connections_as_asset_names: dict) -> dict:
    """For each connection in the message specified by a name, replace that name with the correct entity address."""
    message_with_connections_as_eas = message_with_connections_as_asset_names
    if "connection" in message_with_connections_as_asset_names:
        message_with_connections_as_eas["connection"] = asset_replace_name_with_id(
            parse_as_list(message_with_connections_as_asset_names["connection"]))
    elif "connections" in message_with_connections_as_asset_names:
        message_with_connections_as_eas["connections"] = asset_replace_name_with_id(
            parse_as_list(message_with_connections_as_asset_names["connections"]))
    elif "groups" in message_with_connections_as_asset_names:
        for i, group in enumerate(message_with_connections_as_asset_names["groups"]):
            if "connection" in group:
                message_with_connections_as_eas["groups"][i]["connection"] = asset_replace_name_with_id(
                    parse_as_list(group["connection"]))
            elif "connections" in group:
                message_with_connections_as_eas["groups"][i]["connections"] = asset_replace_name_with_id(
                    parse_as_list(group["connections"]))
    return message_with_connections_as_eas


def asset_replace_name_with_id(connections_as_name: List[str]) -> List[str]:
    """Look up the owner and id given the asset name and constructs a type 1 USEF entity address."""
    connections_as_ea = connections_as_name
    for i, connection in enumerate(connections_as_name):
        scheme_and_naming_authority, owner_id, asset_name = parse_entity_address(connection)
        asset = Asset.query.filter(Asset.name == asset_name).one_or_none()
        asset_id = asset.id
        owner_id = asset.owner_id
        scheme_and_naming_authority = 'ea1.2018-06.com.a1-bvp.api'
        connections_as_ea[i] = "%s:%s:%s" % (scheme_and_naming_authority, owner_id, asset_id)
    return connections_as_name
