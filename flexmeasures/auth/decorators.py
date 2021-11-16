from typing import Optional
from functools import wraps
from flask import current_app
from flask_json import as_json
from flask_security import (
    current_user,
    roles_accepted as roles_accepted_fs,
    roles_required as roles_required_fs,
)
from werkzeug.local import LocalProxy

from flexmeasures.auth.policy import (
    ADMIN_ROLE,
    PERMISSIONS,
    AuthModelMixin,
    user_has_admin_access,
    user_matches_principals,
)


"""
TODO - For developer docs:

FlexMeasures supports the the following role-based decorators:

- roles_accepted
- roles_required
- account_roles_accepted
- account_roles_required

However, these do not qualify on the permission.
A finer auth model is available to distinguish between create, read, write and delete access.
One direct drawback is that the admin-reader role cannot be checked in role-based decorators.

Therefore, we recommend to use the permission_required_for_context decorator.
"""
_security = LocalProxy(lambda: current_app.extensions["security"])


def roles_accepted(*roles):
    """ As in Flask-Security, but also accept admin"""
    if ADMIN_ROLE not in roles:
        roles = roles + (ADMIN_ROLE,)
    return roles_accepted_fs(roles)


def roles_required(*roles):
    """ As in Flask-Security, but wave through if user is admin"""
    if current_user and current_user.has_role(ADMIN_ROLE):
        roles = []
    return roles_required_fs(*roles)


def account_roles_accepted(*account_roles):
    """Decorator which specifies that a user's account must have at least one of the
    specified roles (or must be an admin). Example:

        @app.route('/postMeterData')
        @account_roles_accepted('Prosumer', 'MDC')
        def post_meter_data():
            return 'Meter data posted'

    The current user's account must have either the `Prosumer` role or `MDC` role in
    order to use the service.

    :param account_roles: The possible roles.
    """

    def wrapper(fn):
        @wraps(fn)
        @as_json
        def decorated_service(*args, **kwargs):
            for role in account_roles:
                if current_user and (
                    current_user.account.has_role(role)
                    or current_user.has_role(ADMIN_ROLE)
                ):
                    return fn(*args, **kwargs)
            return _security._unauthz_handler(account_roles_accepted, account_roles)

        return decorated_service

    return wrapper


def account_roles_required(*account_roles):
    """Decorator which specifies that a user's account must have all the specified roles.
    Example::

        @app.route('/dashboard')
        @account_roles_required('Prosumer', 'App-subscriber')
        def dashboard():
            return 'Dashboard'

    The current user's account must have both the `Prosumer` role and
    `App-subscriber` role in order to view the page.

    :param roles: The required roles.
    """

    def wrapper(fn):
        @wraps(fn)
        def decorated_view(*args, **kwargs):
            for role in account_roles:
                if not current_user or (
                    not current_user.account.has_role(role)
                    and not current_user.has_role(ADMIN_ROLE)
                ):
                    return _security._unauthz_handler(
                        account_roles_required, account_roles
                    )
            return fn(*args, **kwargs)

        return decorated_view

    return wrapper


def permission_required_for_context(
    permission: str, arg_pos: Optional[int] = None, arg_name: Optional[str] = None
):
    """
    This decorator can be used to make sure that the current user has the necessary permission to access the context.
    The context needs to be an AuthModelMixin and is found in the keyword arguments by name and/or by a position in the non-keyword arguments (defaults to 0).
    Using both arguments is useful when Marshmallow places a dict of de-serialized fields and you are using use_args.
    The permission needs to be a known permission and is checked with principal descriptions from the context's access control list (see AuthModelMixin.__acl__).

    Usually, you'd place a marshmallow field further up in the decorator chain, e.g.:

        @app.route("/resource/<resource_id>", methods=["GET"])
        @use_kwargs(
            {"the_resource": ResourceIdField(data_key="resource_id")},
            location="path",
        )
        @permission_required_for_context("read", arg_name="the_resource")
        @as_json
        def view(resource_id: int, resource: Resource):
            return dict(name=resource.name)

    Where `ResourceIdField._deserialize()` turns the id parameter into a resource context (if possible).

    This decorator raises a 403 response if there is no principal for the required permission.
    It raises a 401 response if the user is not authenticated at all.
    """

    def wrapper(fn):
        @wraps(fn)
        def decorated_view(*args, **kwargs):
            if permission not in PERMISSIONS:
                current_app.logger.error(
                    f"Permission '{permission}' cannot be handled."
                )
                return _security._unauthz_handler(
                    permission_required_for_context, (permission,)
                )
            if current_user.is_anonymous:
                return _security._unauthn_handler()
            if arg_pos is not None and arg_name is not None:
                context: AuthModelMixin = args[arg_pos][arg_name]
            elif arg_pos is not None:
                context = args[arg_pos]
            elif arg_name is not None:
                context = kwargs[arg_name]
            else:
                context = args[0]
            if not isinstance(context, AuthModelMixin):
                current_app.logger.error(
                    f"Context {context} needs {permission}-permission, but is no AuthModelMixin."
                )
                return _security._unauthz_handler(
                    permission_required_for_context, (permission,)
                )
            if context is None:
                current_app.logger.error(
                    f"Context needs {permission}-permission, but no context was passed."
                )
                return _security._unauthz_handler(
                    permission_required_for_context, (permission,)
                )
            acl = context.__acl__()
            if not user_has_admin_access(
                current_user, permission
            ) and not user_matches_principals(
                current_user, acl.get(permission, tuple())
            ):
                return _security._unauthz_handler(
                    permission_required_for_context, (permission,)
                )
            return fn(*args, **kwargs)

        return decorated_view

    return wrapper
