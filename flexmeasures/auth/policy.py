"""
Tooling & docs for implementing our auth policy
"""

from __future__ import annotations

from flask import current_app
from flask_security import current_user
from werkzeug.exceptions import Unauthorized, Forbidden

# Permissions that custom-role ACLs could grant before role grants were introduced.
LEGACY_ACL_PERMISSIONS = frozenset({"read", "create-children", "update", "delete"})

PERMISSIONS = (
    frozenset(
        {
            "post-data",
            "annotate",
            "trigger-schedules",
            "trigger-forecasts",
            "trigger-reports",
            "manage-automations",
            "edit-flex-config",
            "edit-assets",
            "edit-sensors",
            "delete-data",
            "manage-users",
            "edit-profile",
            "reset-password",
            "edit-account",
        }
    )
    | LEGACY_ACL_PERMISSIONS
)

# User Roles
ADMIN_ROLE = "admin"  # Site-wide full access.
ADMIN_READER_ROLE = "admin-reader"  # Site-wide read access.
ACCOUNT_ADMIN_ROLE = "account-admin"  # Manage one home organisation and its users.
CONSULTANT_ROLE = "consultant"  # Work in client organisations of a consultancy.
ACCOUNT_MEMBER_ROLE = "account-member"  # Operate resources in the home organisation.
ACCOUNT_READER_ROLE = "account-reader"  # Read home organisation resources.
# Post home organisation data and reset one's own password.
ACCOUNT_DATA_INTEGRATOR_ROLE = "account-data-integrator"

# From home-account reading to site-wide administration. The later roles can
# change resource scope, so this is a display order rather than an inheritance chain.
ROLE_DISPLAY_ORDER = (
    ACCOUNT_READER_ROLE,
    ACCOUNT_DATA_INTEGRATOR_ROLE,
    ACCOUNT_MEMBER_ROLE,
    ACCOUNT_ADMIN_ROLE,
    CONSULTANT_ROLE,
    ADMIN_READER_ROLE,
    ADMIN_ROLE,
)

# How roles map to named permissions. This is the main source of truth for our auth policy.
# However, the ACL system allows for more fine-grained control of permissions on a per-resource basis,
# and logic in API endpoints and schemas can further restrict access to certain resources or actions.
# Examples: an account-admin can manage users in their own account, but not in other accounts;
#           a consultant can manage users in their client accounts, but not in other accounts;
#           a consultant can not change the plans for client accounts, nor assign the admin-reader
#           role or the consultant role to client users (see can_modify_role() below).
ROLE_PERMISSION_GRANTS = {
    ACCOUNT_READER_ROLE: frozenset({"read"}),
    ACCOUNT_DATA_INTEGRATOR_ROLE: frozenset({"read", "post-data", "reset-password"}),
    ACCOUNT_MEMBER_ROLE: PERMISSIONS - {"delete-data", "manage-users", "delete"},
    ACCOUNT_ADMIN_ROLE: PERMISSIONS,
    CONSULTANT_ROLE: PERMISSIONS,
    ADMIN_READER_ROLE: frozenset({"read"}),
    ADMIN_ROLE: PERMISSIONS,
}

# Account Roles
CONSULTANCY_ACCOUNT_ROLE = "Consultancy"

# constants to allow access to certain groups
EVERY_LOGGED_IN_USER = "every-logged-in-user"
PRINCIPALS_TYPE = str | tuple[str] | list[str | tuple[str] | None] | None


class AuthModelMixin(object):
    def __acl__(self) -> dict[str, PRINCIPALS_TYPE]:
        """
        This function returns an access control list (ACL) for an instance of a model which is relevant for authorization.

        ACLs in FlexMeasures are inspired by Pyramid's resource ACLs.
        Each ACL key is a named permission (for example, ``trigger-schedules``).
        The user needs that permission from an eligible role and must match a
        principal under the same key. Home roles apply to the user's own account;
        consultant applies through a consultancy principal on client resources.

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

        Empty principals (e.g. None, an empty list, tuple or string) will not match and the user will not be given the permission.
        We want to prevent accidental bugs this way. If you provide access, do it explicitly.

        # Row-level authorization

        This ACL approach to authorization is usually called "row-level authorization" ― it always requires an instance, from which to get the ACL.
        Unlike pyramid, we don't have a general solution for table-level auth (as we haven't needed a general implementation so far), but there is a nice custom approach to it.
        A class method on the model can be added which returns an AuthModelMixin. That would have an __acl__() function with your rules, which the auth policy will then go on and use. The permission_required_for_context decorator can make sure this AuthModelMixin object is used by the policy via ctx_loader. It can even pass in the context if that is helpful for your logic.
        See the AuditLog model class for an example, where we required authorization logic which governs if a subset of a table (e.g. all audit logs that relate to an account) are availabe to the current user."

        Row level access policy works because we make use of the hierarchy in our model.
        The highest level (e.g. an account) is created by site-admins and usually not in the API, but CLI. For everything else, we can ask the ACL
        on an instance, if we can handle it like we intend to. For creation of instances (where there is no instance to ask), it makes sense to use the instance one level up to look up the correct permission ("create-children"). E.g. to create belief data for a sensor, we can check the "create-children" - permission on the sensor.

        [1] https://docs.microsoft.com/en-us/windows/security/identity-protection/access-control/security-principals#a-href-idw2k3tr-princ-whatawhat-are-security-principals
        """
        return {}


class FlexMeasuresPlatform(AuthModelMixin):
    """Virtual platform resource to authorize top-level creations."""

    @classmethod
    def init(cls, context: dict | None = None) -> "FlexMeasuresPlatform":
        return cls()

    def __acl__(self):
        create_accounts = [  # this applies to accounts
            f"role:{ADMIN_ROLE}",
            (  # FM makes sure the new accounts are clients of the consultant account
                f"role:{CONSULTANT_ROLE}",
                f"account-role:{CONSULTANCY_ACCOUNT_ROLE}",
            ),
        ]
        return {
            "edit-account": create_accounts,
            # Compatibility for callers still checking the broad CRUD permission.
            "create-children": create_accounts,
        }


def check_access(context: AuthModelMixin, permission: str):
    """
    Check if current user can access this auth context if this permission
    is required, either with admin rights or principal(s).

    Raises 401 or 403 otherwise.
    """
    # check permission and current user before taking context into account
    if permission not in PERMISSIONS:
        raise Forbidden(f"Permission '{permission}' cannot be handled.")
    if current_user.is_anonymous:
        raise Unauthorized()

    # check context
    if context is None:
        raise Forbidden(
            f"Context needs {permission}-permission, but no context was passed."
        )
    if not isinstance(context, AuthModelMixin):
        raise Forbidden(
            f"Context {context} needs {permission}-permission, but is no AuthModelMixin."
        )

    # look up principals
    acl = context.__acl__()
    principals: PRINCIPALS_TYPE = acl.get(permission, [])
    current_app.logger.debug(
        f"Looking for {permission}-permission on {context} ... Principals: {principals}"
    )

    # A role grant and an ACL alternative must match in the same scope.
    if not user_has_admin_access(
        current_user, permission
    ) and not user_has_scoped_permission(current_user, permission, principals):
        raise Forbidden(
            f"Authorization failure (accessing {context} to {permission}) ― cannot match {current_user} against {principals}!"
        )


def user_can_reset_own_password(user) -> bool:
    """Allow self-service password recovery only with an eligible role grant."""
    return any("reset-password" in role.permissions for role in user.roles)


def user_has_admin_access(user, permission: str) -> bool:
    if user.has_role(ADMIN_ROLE) or (
        user.has_role(ADMIN_READER_ROLE) and permission == "read"
    ):
        return True
    return False


def _custom_role_grants_legacy_permission(
    user, permission: str, principals: tuple[str, ...], explicit_roles: set[str]
) -> bool:
    """Keep explicit custom-role grants on preexisting ACL permissions."""
    if permission not in LEGACY_ACL_PERMISSIONS:
        return False
    custom_roles = explicit_roles - ROLE_PERMISSION_GRANTS.keys()
    if not any(user.has_role(role) for role in custom_roles):
        return False
    # Check the whole tuple because the principal matcher short-circuits on this wildcard.
    required_principals = tuple(
        principal for principal in principals if principal != EVERY_LOGGED_IN_USER
    )
    return user_matches_principals(user, required_principals)


def user_has_scoped_permission(
    user, permission: str, principals: PRINCIPALS_TYPE
) -> bool:
    """Require a scoped role grant or an explicit legacy custom-role ACL grant."""
    alternatives = principals if isinstance(principals, list) else [principals]
    for alternative in alternatives:
        if not alternative or not user_matches_principals(user, alternative):
            continue
        alternative_principals = (
            (alternative,) if isinstance(alternative, str) else alternative
        )
        explicit_roles = {
            principal.removeprefix("role:")
            for principal in alternative_principals
            if principal.startswith("role:")
        }
        if explicit_roles:
            if _custom_role_grants_legacy_permission(
                user, permission, alternative_principals, explicit_roles
            ):
                return True
            eligible_roles = explicit_roles
        elif EVERY_LOGGED_IN_USER in alternative_principals:
            eligible_roles = {role.name for role in user.roles}
        else:
            eligible_roles = {
                role.name for role in user.roles if role.name != CONSULTANT_ROLE
            }
        if any(
            role.name in eligible_roles and permission in role.permissions
            for role in user.roles
        ):
            return True
    return False


def user_matches_principals(user, principals: PRINCIPALS_TYPE) -> bool:
    """
    Tests if the user matches all passed principals.
    Returns False if no principals are passed.
    """
    if not isinstance(principals, list):
        principals = [principals]  # now we handle a list of str or tuple[str]
    for matchable_principals in principals:
        if matchable_principals is None or len(matchable_principals) == 0:
            continue  # these cases will not evaluate to True, rather use the explicit case (see below)
        if isinstance(matchable_principals, str):
            matchable_principals = (
                matchable_principals,
            )  # now we handle only tuple[str]
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


def can_modify_role(  # noqa: C901
    user,
    roles_to_modify,
    modified_user,
) -> bool:
    """For a set of supported roles, check if the current user can modify the roles.

    :param user: The current attempting to modify a role.
    :param roles_to_modify: A list of roles to modify - can be a Role or a role ID.
    :param modified_user: The user whose roles are being modified.
    :return: True if the user can modify each of the roles, False otherwise.

    The roles are:
    - admin: can only be changed in CLI / directly in the DB, so not here
    - admin-reader: can be added and removed by admins
    - account-admin: can be added and removed by admins and consultants (in consultancy account)
    - consultant: can be added and removed by admins and account-admins (in same account)
    - account-member, account-reader, account-data-integrator: can be changed by admins, account-admins
      of the user's account, and consultants of its consultancy account

    """
    roles = []
    for role in roles_to_modify:
        if isinstance(role, int):
            from flexmeasures.data.models.user import Role

            roles.append(current_app.db.session.get(Role, role))
        else:
            roles.append(role)

    if not roles:
        return False

    for role in roles:
        if role is None:
            return False
        if role.name == ADMIN_ROLE:
            # Nobody can do this here, only in CLI or directly in the DB.
            return False
        if role.name == ADMIN_READER_ROLE:
            # only admins can change admin-reader status
            if user.has_role(ADMIN_ROLE):
                continue
            return False
        if role.name == ACCOUNT_ADMIN_ROLE:
            # admins and consultants can do this
            if user.has_role(ADMIN_ROLE):
                continue
            if (
                modified_user.account.consultancy_account is not None
                and user.has_role(CONSULTANT_ROLE)
                and user.account.id == modified_user.account.consultancy_account.id
            ):
                continue
            return False
        if role.name == CONSULTANT_ROLE:
            # admins and account-admins can do this
            if user.has_role(ADMIN_ROLE):
                continue
            if (
                user.has_role(ACCOUNT_ADMIN_ROLE)
                and user.account.id == modified_user.account.id
            ):
                continue
            return False
        if role.name in (
            ACCOUNT_MEMBER_ROLE,
            ACCOUNT_READER_ROLE,
            ACCOUNT_DATA_INTEGRATOR_ROLE,
        ):
            if user.has_role(ADMIN_ROLE):
                continue
            if (
                user.has_role(ACCOUNT_ADMIN_ROLE)
                and user.account.id == modified_user.account.id
            ):
                continue
            if (
                user.has_role(CONSULTANT_ROLE)
                and modified_user.account.consultancy_account_id == user.account.id
            ):
                continue
            return False
        return False

    return True


def user_can_add_accounts() -> bool:
    """Check if the current user can create new accounts.

    Uses the ACL system to verify the user has permission to create
    accounts on the FlexMeasures platform.

    :return: True if user has permission, False otherwise.
    """
    try:
        check_access(FlexMeasuresPlatform.init(), "create-children")
        return True
    except (Forbidden, Unauthorized):
        return False
