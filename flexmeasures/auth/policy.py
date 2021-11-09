from typing import Dict, Union, Tuple

from flask import current_app
from flask_security import current_user


PERMISSIONS = ["create", "read", "write", "delete"]

ADMIN_ROLE = "admin"
ADMIN_READER_ROLE = "admin-reader"

# constants to allow access to certain groups
EVERYONE = "everyone"


class AuthModelMixin(object):
    def __acl__(self) -> Dict[str, Union[str, Tuple[str]]]:
        """
        Access control list for a resource (class or instance). Inspired by Pyramid's resource ACLs.

        This function returns a mapping of permissions to principal descriptors.

        In computer security, a principal is the security context of the authenticated user [1].
        In the access control list, we list which principal aspects allow certain kinds of actions.

        In these access control lists, we allow to codify user and account roles, as well as user and account IDs.

        Here are some (fictional) examples:

        {
            "create": "account:3",               # Everyone in Account 3 can create
            "read": EVERYONE,                    # Reading is available to every logged-in user
            "write": "user:14",                  # This user can write, ...
            "write": "user:15",                  # and also this user, ...
            "write": "account-role:MDC",         # also people in such accounts can write
            "delete": ("account:3", "role:CEO"), # Only CEOs of Account 3 can create
        }

        Notes:

        - Iterable principal descriptors should be treated as to be AND-connected. This helps to define subsets,
          like the deletion example.
        - Some of these are only possible with an object loaded (row-level authorization). The __acl__
          implementation needs to take care of that.

        Such a list of principals can be checked with match_principals, see below.

        [1] https://docs.microsoft.com/en-us/windows/security/identity-protection/access-control/security-principals#a-href-idw2k3tr-princ-whatawhat-are-security-principals
        """
        return {}


def match_principals(principals: Union[str, Tuple[str]]):
    """
    Tests if current user matches at least one principal.
    """
    if isinstance(principals, str):
        principals = (principals,)
    if EVERYONE in principals:
        return True
    if current_user is None:
        return False
    for principal in principals:
        if check_user_identity(principal):
            return True
        if check_user_role(principal):
            return True
        if check_account_membership(principal):
            return True
        if check_account_role(principal):
            return True
    current_app.logger.error(
        f"Authorization failure ― Cannot match {current_user} against {principals}!"
    )
    return False


def check_user_identity(principal: str) -> bool:
    if principal.startswith("user:"):
        user_id = principal.split("user:")[1]
        if not user_id.isdigit():
            current_app.logger.warning(
                f"Cannot match principal for user ID {user_id} ― no digit."
            )
        elif current_user.id == int(user_id):
            return True
    return False


def check_user_role(principal: str) -> bool:
    if principal.startswith("role:"):
        user_role = principal.split("role:")[1]
        if current_user.has_role(user_role):
            return True
    return False


def check_account_membership(principal: str) -> bool:
    if principal.startswith("account:"):
        account_id = principal.split("account:")[1]
        if not account_id.isdigit():
            current_app.logger.warning(
                f"Cannot match principal for account ID {account_id} ― no digit."
            )
        elif current_user.account.id == int(account_id):
            return True
    return False


def check_account_role(principal: str) -> bool:
    if principal.startswith("account-role:"):
        account_role = principal.split("account-role:")[1]
        if current_user.account.has_role(account_role):
            return True
    return False
