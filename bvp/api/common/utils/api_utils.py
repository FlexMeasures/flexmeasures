import copy
from typing import List, Tuple, Union
import re

from bvp.data.models.assets import Asset


def check_access(service_listing, service_name):
    """
    For a given USEF service name (API endpoint) in a service listing,
    return the list of USEF roles that are allowed to access the service.
    """
    return next(
        service["access"]
        for service in service_listing["services"]
        if service["name"] == service_name
    )


def parse_entity_address(
    entity_address: str
) -> Tuple[str, Union[int, str], Union[int, str]]:
    """
    Parse an entity address into scheme_and_naming_authority, owner_id, and asset_id.

    :param entity_address: id following the EA1 addressing scheme recommended by USEF, for example:
                           'ea1.2018-06.com.a1-bvp.api:<owner-id>:<asset-id>'
    :return: scheme and naming authority (a string), id of the asset's owner (an integer or string),
             and id of the asset (an integer or string).
             If the owner or asset id is a string, you could still try to look for the owner or asset by name.
    """
    asset_id_match = re.findall("(?<=:)\d+$", entity_address)
    if asset_id_match:
        asset_id = asset_id_match[-1]
    else:
        return "", "", entity_address
    owner_id_match = re.findall("(?<=:)\d+(?=:\d+$)", entity_address)
    if owner_id_match:
        owner_id = owner_id_match[-1]
    else:
        owner_id = ""
    scheme_and_naming_authority_match = re.findall(".+(?=:\d+:\d+$)", entity_address)
    if scheme_and_naming_authority_match:
        scheme_and_naming_authority = scheme_and_naming_authority_match[-1]
    else:
        scheme_and_naming_authority = ""

    if owner_id.isdigit():
        owner_id = int(owner_id)
    if asset_id.isdigit():
        asset_id = int(asset_id)

    return scheme_and_naming_authority, owner_id, asset_id


def contains_empty_items(groups: List[List[str]]):
    """
    Return True if any of the items in the groups is empty.
    """
    for group in groups:
        for item in group:
            if item == "" or item is None:
                return True
    return False


def parse_as_list(connection: Union[List[str], str]) -> List[str]:
    """
    Return a list of connections, even if it's just one connection
    """
    if isinstance(connection, str):
        connections = [connection]
    elif isinstance(connection, list):  # key should have been plural
        connections = connection
    else:
        connections = []
    return connections


def get_form_from_request(_request) -> Union[dict, None]:
    if _request.method == "GET":
        d = _request.args.to_dict(
            flat=False
        )  # From MultiDict, obtain all values with the same key as a list
        return dict(
            zip(d.keys(), [v[0] if len(v) == 1 else v for k, v in d.items()])
        )  # Flatten single-value lists
    elif _request.method == "POST":
        return _request.get_json(force=True)
    else:
        return None


def append_doc_of(fun):
    def decorator(f):
        if f.__doc__:
            f.__doc__ += fun.__doc__
        else:
            f.__doc__ = fun.__doc__
        return f

    return decorator


def groups_to_dict(
    connection_groups: List[List[str]], value_groups: List[List[str]]
) -> dict:
    """Put the connections and values in a dictionary and simplify if groups have identical values and/or if there is
    only one group.

    Examples:

        >> connection_groups = [[1]]
        >> value_groups = [[300, 300, 300]]
        >> response_dict = groups_to_dict(connection_groups, value_groups)
        >> print(response_dict)
        <<  {
                "connection": 1,
                "values": [300, 300, 300]
            }

        >> connection_groups = [[1], [2]]
        >> value_groups = [[300, 300, 300], [300, 300, 300]]
        >> response_dict = groups_to_dict(connection_groups, value_groups)
        >> print(response_dict)
        <<  {
                "connections": [1, 2],
                "values": [300, 300, 300]
            }

        >> connection_groups = [[1], [2]]
        >> value_groups = [[300, 300, 300], [400, 400, 400]]
        >> response_dict = groups_to_dict(connection_groups, value_groups)
        >> print(response_dict)
        <<  {
                "groups": [
                    {
                        "connection": 1,
                        "values": [300, 300, 300]
                    },
                    {
                        "connection": 2,
                        "values": [400, 400, 400]
                    }
                ]
            }
    """

    # Simplify groups that have identical values
    value_groups, connection_groups = unique_ever_seen(value_groups, connection_groups)

    # Simplify if there is only one group
    if len(value_groups) == len(connection_groups) == 1:
        if len(connection_groups[0]) == 1:
            return {"connection": connection_groups[0][0], "values": value_groups[0]}
        else:
            return {"connections": connection_groups[0], "values": value_groups[0]}
    else:
        d = {"groups": []}
        for connection_group, value_group in zip(connection_groups, value_groups):
            if len(connection_group) == 1:
                d["groups"].append(
                    {"connection": connection_group[0], "values": value_group}
                )
            else:
                d["groups"].append(
                    {"connections": connection_group, "values": value_group}
                )
        return d


def unique_ever_seen(iterable, selector):
    """
    Return unique iterable elements with corresponding lists of selector elements, preserving order.
    """
    u = []
    s = []
    for iterable_element, selector_element in zip(iterable, selector):
        if iterable_element not in u:
            u.append(iterable_element)
            s.append(selector_element)
        else:
            us = s[u.index(iterable_element)]
            if not isinstance(us, list):
                us = [us]
            us.append(selector_element)
            s[u.index(iterable_element)] = us
    return u, s


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
