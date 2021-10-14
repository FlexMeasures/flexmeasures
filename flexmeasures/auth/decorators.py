from functools import wraps
from flask import current_app
from flask_json import as_json
from flask_security import (
    current_user,
    roles_accepted as roles_accepted_fs,
    roles_required as roles_required_fs,
)
from werkzeug.local import LocalProxy

from flexmeasures.auth.policy import ADMIN_ROLE


"""
For docs:
in FlexMeasures, we recommend to make use of the following decorators:

- roles_accepted
- roles_required
- account_roles_accepted
- account_roles_required

However, these do not work on admin-reader.

Better to use the decorators we will create in a PR soon.
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
                if (
                    current_user
                    and current_user.account.has_role(role)
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
                if not current_user or not current_user.account.has_role(role):
                    return _security._unauthz_handler(
                        account_roles_required, account_roles
                    )
            return fn(*args, **kwargs)

        return decorated_view

    return wrapper
