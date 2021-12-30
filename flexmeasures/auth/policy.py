from typing import Dict, Union, Tuple, List

from flask import current_app


PERMISSIONS = ["create-children", "read", "read-children", "update", "delete"]

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
            "create-children": "account:3",      # Everyone in Account 3 can create child items (e.g. beliefs for a sensor)
            "read": EVERYONE,                    # Reading is available to every logged-in user
            "update": ["user:14",                # This user can update, ...
                        user:15"],               # and also this user, ...
            "update": "account-role:MDC",        # also people in such accounts can update
            "delete": ("account:3", "role:CEO"), # Only CEOs of Account 3 can delete
        }

        Such a list of principals can be checked with match_principals, see below.

        Notes:

        - Iterable principal descriptors should be treated as follows: a list is OR-connected. A tuple is AND-connected. This helps to define subsets,
          like the update and deletion example above. You could have a list of tuples.
        - This is row-level authorization, which always requires an instance. We make use of the hierarchy in our model ― for creation of instances,
        it makes sense to use the instance one level up to look up the correct permission ("create-children"). E.g. to create belief data for a sensor, we can check the create-permission on the sensor.

        [1] https://docs.microsoft.com/en-us/windows/security/identity-protection/access-control/security-principals#a-href-idw2k3tr-princ-whatawhat-are-security-principals
        """
        return {}


def user_has_admin_access(user, permission: str) -> bool:
    if user.has_role(ADMIN_ROLE) or (
        user.has_role(ADMIN_READER_ROLE) and permission == "read"
    ):
        return True
    return False


def user_matches_principals(
    user, principals: Union[str, Tuple[str], List[Union[str, Tuple[str]]]]
) -> bool:
    """
    Tests if the user matches all passed principals.
    Returns False if no principals are passed.
    """
    if not isinstance(principals, list):
        principals = [principals]  # now we handle a list of str or Tuple[str]
    for matchable_principals in principals:
        if isinstance(matchable_principals, str):
            matchable_principals = (
                matchable_principals,
            )  # now we handle only Tuple[str]
        if EVERYONE in matchable_principals:
            return True
        if user is not None and all(
            [
                (
                    check_user_identity(user, principal)
                    or check_user_role(user, principal)
                    or check_account_membership(user, principal)
                    or check_account_role(user, principal)
                )
                for principal in matchable_principals
            ]
        ):
            return True
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
