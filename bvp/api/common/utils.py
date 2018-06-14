from typing import List, Tuple, Union


def sender_has_allowed_role(user, roles: Union[List[str], str]) -> bool:
    if not isinstance(roles, list):
        roles = [roles]
    validated = False
    for role in roles:
        if user.has_role(role):
            validated = True
    return validated


def message_has_allowed_unit(unit: str) -> bool:
    # TODO: properly handle units (comparing the unit in the request to the unit used for data in the database)
    if unit == 'MW':
        return True
    else:
        return False


def parse_asset_identifier(asset_identifier: str) -> Tuple[str, str, str]:
    """Parse an asset identifier into scheme_and_naming_authority, owner, and asset name or id"""
    scheme_and_naming_authority, owner, asset = "", "", ""
    if asset_identifier.count(":") == 2:
        scheme_and_naming_authority, owner, asset = asset_identifier.split(":", 2)
    elif asset_identifier.count(":") == 1:
        owner, asset = asset.split(":", 1)
    elif asset_identifier.count(":") == 0:
        asset = asset_identifier
    return scheme_and_naming_authority, owner, asset
