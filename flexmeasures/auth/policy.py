from typing import Dict, Union, Tuple, List

from flask import current_app


PERMISSIONS = ["create-children", "read", "read-children", "update", "delete"]

ADMIN_ROLE = "admin"
ADMIN_READER_ROLE = "admin-reader"

# constants to allow access to certain groups
EVERY_LOGGED_IN_USER = "every-logged-in-user"

PRINCIPALS_TYPE = Union[str, Tuple[str], List[Union[str, Tuple[str]]]]


class AuthModelMixin(object):
    def __acl__(self) -> Dict[str, PRINCIPALS_TYPE]:
        """
        This function returns an access control list (ACL) for a instance of a model which is relevant for authorization.

        ACLs in FlexMeasures are inspired by Pyramid's resource ACLs.
        In an ACL, we list which principal (security contexts, see below) allow certain kinds of actions
        ― by mapping supported permissions to the required principals.

        # What is a principal / security context?

        In computer security, a "principal" is the security context of the authenticated user [1].
        For example, within FlexMeasures, an accepted principal is "user:2", which denotes that the user should have ID 2
        (more technical specifications follow below).

        # Example

        Here are some examples of principals mapped to permissions in a fictional ACL:

        {
            "create-children": "account:3",      # Everyone in Account 3 can create child items (e.g. beliefs for a sensor)
            "read": EVERYONE,                    # Reading is available to every logged-in user
            "update": ["user:14",                # This user can update, ...
                        user:15"],               # and also this user, ...
            "update": "account-role:MDC",        # also people in such accounts can update
            "delete": ("account:3", "role:CEO"), # Only CEOs of Account 3 can delete
        }

        Such a list of principals can be checked with match_principals, see below.

        # Specifications of principals

        Within FlexMeasures, a principal is handled as a string, usually defining context and identification, like so:

            <context>:<identification>.

        Supported contexts are user and account IDs, as well as user and account roles. All of them feature in the example above.

        Iterable principal descriptors should be treated as follows:
        - a list contains OR-connected items, which can be principal or tuples of principals (one of the items in the list is sufficient to grant the permission)
        - a tuple contains AND-connected strings (you need all of the items in the list to grant the permission).

        # Row-level authorization

        This ACL approach to authorization is usually called "row-level authorization" ― it always requires an instance, from which to get the ACL.
        Unlike pyramid, we have not implemented table-level authorization, where a class also can provide an ACL.
        This works because we make use of the hierarchy in our model.
        The highest level (e.g. an account) is created by site-admins and usually not in the API, but CLI. For everything else, we can ask the ACL
        on an instance, if we can handle it like we intend to. For creation of instances (where there is no instance to ask), it makes sense to use the instance one level up to look up the correct permission ("create-children"). E.g. to create belief data for a sensor, we can check the "create-children" - permission on the sensor.

        [1] https://docs.microsoft.com/en-us/windows/security/identity-protection/access-control/security-principals#a-href-idw2k3tr-princ-whatawhat-are-security-principals
        """
        return {}


def user_has_admin_access(user, permission: str) -> bool:
    if user.has_role(ADMIN_ROLE) or (
        user.has_role(ADMIN_READER_ROLE) and permission == "read"
    ):
        return True
    return False


def user_matches_principals(user, principals: PRINCIPALS_TYPE) -> bool:
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
        if EVERY_LOGGED_IN_USER in matchable_principals:
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
