"""
Auth decorators for endpoints
"""


from __future__ import annotations

from typing import Callable
from functools import wraps
import inspect
from flask import current_app
from flask_json import as_json
from flask_security import (
    current_user,
    roles_accepted as roles_accepted_fs,
    roles_required as roles_required_fs,
)
from werkzeug.local import LocalProxy
from werkzeug.exceptions import Forbidden
from flexmeasures.data import db
from flexmeasures.auth.policy import ADMIN_ROLE, AuthModelMixin, check_access


_security = LocalProxy(lambda: current_app.extensions["security"])


def roles_accepted(*roles):
    """As in Flask-Security, but also accept admin"""
    if ADMIN_ROLE not in roles:
        roles = roles + (ADMIN_ROLE,)
    return roles_accepted_fs(*roles)


def roles_required(*roles):
    """As in Flask-Security, but wave through if user is admin"""
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
            if current_user and (
                current_user.has_role(ADMIN_ROLE)
                or any([current_user.account.has_role(role) for role in account_roles])
            ):
                return fn(*args, **kwargs)
            raise Forbidden(
                f"User {current_user}'s account does not have any of the following roles: {','.join(account_roles)}."
            )

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
            if not current_user or (
                not current_user.has_role(ADMIN_ROLE)
                and not all(
                    [current_user.account.has_role(role) for role in account_roles]
                )
            ):
                raise Forbidden(
                    f"User {current_user}'s account does not have all of the following roles: {','.join(account_roles)}."
                )
            return fn(*args, **kwargs)

        return decorated_view

    return wrapper


def permission_required_for_context(
    permission: str,
    ctx_arg_pos: int | None = None,
    ctx_arg_name: str | None = None,
    ctx_loader: Callable | None = None,
    pass_ctx_to_loader: bool = False,
):
    """
    This decorator can be used to make sure that the current user has the necessary permission to access the context.
    The permission needs to be a known permission and is checked with principal descriptions from the context's access control list (see AuthModelMixin.__acl__).
    This decorator will first load the context (see below for details) and then call check_access to make sure the current user has the permission.

    A 403 response is raised if there is no principal for the required permission.
    A 401 response is raised if the user is not authenticated at all.

    We will now explain how to load a context, and give an example:

    The context needs to be an AuthModelMixin and is found ...
    - by loading it via the ctx_loader callable;
    - otherwise:
      * by the keyword argument ctx_arg_name;
      * and/or by a position in the non-keyword arguments (ctx_arg_pos).
    If nothing is passed, the context lookup defaults to ctx_arg_pos=0.

    Let's look at an example. Usually, you'd place a marshmallow field further up in the decorator chain, e.g.:

        @app.route("/resource/<resource_id>", methods=["GET"])
        @use_kwargs(
            {"the_resource": ResourceIdField(data_key="resource_id")},
            location="path",
        )
        @permission_required_for_context("read", ctx_arg_name="the_resource")
        @as_json
        def view(resource_id: int, the_resource: Resource):
            return dict(name=the_resource.name)

    Note that in this example, `ResourceIdField._deserialize()` turns the id parameter into a Resource context (if possible).

    The ctx_loader:

      The ctx_loader can be a function without arguments or it takes the context loaded from the arguments as input (using pass_ctx_to_loader=True).
      A special case is useful when the arguments contain the context ID (not the instance).
      Then, the loader can be a subclass of AuthModelMixin, and this decorator will look up the instance.

    Using both arg name and position:

      Using both ctx_arg_name and ctx_arg_pos arguments is useful when Marshmallow de-serializes to a dict and you are using use_args. In this case, the context lookup applies first ctx_arg_pos, then ctx_arg_name.

    Let's look at a slightly more complex example where we combine both special cases from above.
    We parse a dictionary from the input with a Marshmallow schema, in which a context ID can be found which we need to instantiate:

        @app.route("/resource", methods=["POST"])
        @use_args(resource_schema)
        @permission_required_for_context(
            "create-children", ctx_arg_pos=1, ctx_arg_name="resource_id", ctx_loader=Resource, pass_ctx_to_loader=True
        )
        def post(self, resource_data: dict):
    Note that in this example, resource_data is the input parsed by resource_schema, "resource_id" is one of the parameters in this schema, and Resource is a subclass of AuthModelMixin.
    """

    def wrapper(fn):
        @wraps(fn)
        def decorated_view(*args, **kwargs):
            # load & check context
            context: AuthModelMixin = None

            # first set context_from_args, if possible
            context_from_args: AuthModelMixin = None
            if ctx_arg_pos is not None and ctx_arg_name is not None:
                context_from_args = args[ctx_arg_pos][ctx_arg_name]
            elif ctx_arg_pos is not None:
                context_from_args = args[ctx_arg_pos]
            elif ctx_arg_name is not None:
                context_from_args = kwargs[ctx_arg_name]
            elif len(args) > 0:
                context_from_args = args[0]

            # if a loader is given, use that, otherwise fall back to context_from_args
            if ctx_loader is not None:
                if pass_ctx_to_loader:
                    if inspect.isclass(ctx_loader) and issubclass(
                        ctx_loader, AuthModelMixin
                    ):
                        context = db.session.get(ctx_loader, context_from_args)
                    else:
                        context = ctx_loader(context_from_args)
                else:
                    context = ctx_loader()
            else:
                context = context_from_args

            check_access(context, permission)

            return fn(*args, **kwargs)

        return decorated_view

    return wrapper
