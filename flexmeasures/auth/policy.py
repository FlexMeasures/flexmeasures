from typing import Dict, Union, Tuple

from flask import current_app


PERMISSIONS = ["create", "read", "write", "delete"]

ADMIN_ROLE = "admin"
ADMIN_READER_ROLE = "admin-reader"

# constants to allow access to certain groups
EVERYONE = "everyone"


class AuthModelMixin(object):
    def __acl__(self) -> Dict[str, Union[str, Tuple[str]]]:
        """
        Access control list for a resource instance. Inspired by Pyramid's resource ACLs.

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

        Such a list of principals can be checked with match_principals, see below.

        Notes:

        - Iterable principal descriptors should be treated as to be AND-connected. This helps to define subsets,
          like the deletion example above.
        - This is row-level authorization, which requires an instance. We are considering table-level authorization, which wouldn't, so it would allow for faster authorization checks if no instances are needed.

        [1] https://docs.microsoft.com/en-us/windows/security/identity-protection/access-control/security-principals#a-href-idw2k3tr-princ-whatawhat-are-security-principals
        """
        return {}


def user_has_admin_access(user, permission: str) -> bool:
    if user.has_role(ADMIN_ROLE) or (
        user.has_role(ADMIN_READER_ROLE) and permission == "read"
    ):
        return True
    return False


def user_matches_principals(user, principals: Union[str, Tuple[str]]):
    """
    Tests if the user matches all passed principals.
    Returns False if no principals are passed.
    """
    if isinstance(principals, str):
        principals = (principals,)
    if EVERYONE in principals:
        return True
    if user is None:
        return False
    if all(
        [
            (
                check_user_identity(user, principal)
                or check_user_role(user, principal)
                or check_account_membership(user, principal)
                or check_account_role(user, principal)
            )
            for principal in principals
        ]
    ):
        return True
    current_app.logger.error(
        f"Authorization failure ― cannot match {user} against {principals}!"
    )
    return False


def check_user_identity(user, principal: str) -> bool:
    if principal.startswith("user:"):
        user_id = principal.split("user:")[1]
        if not user_id.isdigit():
            current_app.logger.warning(
                f"Cannot match principal for user ID {user_id} ― no digit."
            )
        elif user.id == int(user_id):
            return True
    return False


def check_user_role(user, principal: str) -> bool:
    if principal.startswith("role:"):
        user_role = principal.split("role:")[1]
        if user.has_role(user_role):
            return True
    return False


def check_account_membership(user, principal: str) -> bool:
    if principal.startswith("account:"):
        account_id = principal.split("account:")[1]
        if not account_id.isdigit():
            current_app.logger.warning(
                f"Cannot match principal for account ID {account_id} ― no digit."
            )
        elif user.account.id == int(account_id):
            return True
    return False


def check_account_role(user, principal: str) -> bool:
    if principal.startswith("account-role:"):
        account_role = principal.split("account-role:")[1]
        if user.account.has_role(account_role):
            return True
    return False
