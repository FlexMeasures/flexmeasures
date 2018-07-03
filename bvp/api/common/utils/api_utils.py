from typing import List, Tuple, Union


def update_beliefs():
    """
    Store the data in the power forecasts table.
    """
    return


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

    scheme_and_naming_authority, owner_id, asset_id = "", "", ""
    if entity_address.count(":") == 2:
        scheme_and_naming_authority, owner_id, asset_id = entity_address.split(":", 2)
    elif entity_address.count(":") == 1:
        owner_id, asset_id = asset_id.split(":", 1)
    elif entity_address.count(":") == 0:
        asset_id = entity_address
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
        return _request.args
    elif _request.method == "POST":
        return _request.get_json(force=True)
    else:
        return None
