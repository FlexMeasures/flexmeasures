import re

from functools import wraps

from flask import request, current_app
from flask_json import as_json
from flask_principal import Permission, RoleNeed
from flask_security import current_user

from bvp.api.common.responses import (  # noqa: F401
    invalid_domain,
    invalid_method,
    invalid_message_type,
    invalid_sender,
    invalid_timezone,
    invalid_unit,
    no_message_type,
    ptus_incomplete,
    unrecognized_connection_group,
)
from bvp.api.common.utils.api_utils import (
    get_form_from_request,
    parse_as_list,
    contains_empty_items,
)


def validate_entity_address(connection: str) -> str:
    """
    Validates whether the string 'connection' is a valid type 1 USEF entity address.
    """
    match = re.search(".+\.\d{4}-\d{2}\..+:\d+:\d+", connection)
    if match:
        return match.string


def connections_required(fn):
    """Decorator which specifies that a GET or POST request must specify one or more connections.
    Example:

        @app.route('/postMeterData')
        @connections_required
        def post_meter_data(connection_groups):
            return 'Meter data posted'

    The message must specify one or more connections. If that is the case, then the connections are passed to the
    function as connection_groups.
    """

    @wraps(fn)
    @as_json
    def wrapper(*args, **kwargs):
        form = get_form_from_request(request)
        if form is None:
            current_app.logger.warn(
                "Unsupported request method for unpacking 'connections' from request."
            )
            return invalid_method(request.method)

        if "connection" in form:
            connection_groups = [parse_as_list(form["connection"])]
        elif "connections" in form:
            connection_groups = [parse_as_list(form["connections"])]
        elif "groups" in form:
            connection_groups = []
            for group in form["groups"]:
                if "connection" in group:
                    connection_groups.append(parse_as_list(group["connection"]))
                elif "connections" in group:
                    connection_groups.append(parse_as_list(group["connections"]))
                else:
                    current_app.logger.warn("Group %s missing connection(s)" % group)
                    return unrecognized_connection_group()
        else:
            current_app.logger.warn("Request missing connection(s) or group.")
            return unrecognized_connection_group()

        if not contains_empty_items(connection_groups):
            kwargs["connection_groups"] = connection_groups
            return fn(*args, **kwargs)
        else:
            current_app.logger.warn("Request includes empty connection(s).")
            return unrecognized_connection_group()

    return wrapper


def values_required(fn):
    """Decorator which specifies that a GET or POST request must specify one or more values.
    Example:

        @app.route('/postMeterData')
        @values_required
        def post_meter_data(value_groups):
            return 'Meter data posted'

    The message must specify one or more values. If that is the case, then the values are passed to the
    function as value_groups.
    """

    @wraps(fn)
    @as_json
    def wrapper(*args, **kwargs):
        form = get_form_from_request(request)
        if form is None:
            current_app.logger.warn(
                "Unsupported request method for unpacking 'values' from request."
            )
            return invalid_method(request.method)

        if "value" in form:
            value_groups = [parse_as_list(form["value"])]
        elif "values" in form:
            value_groups = [parse_as_list(form["values"])]
        elif "groups" in form:
            value_groups = []
            for group in form["groups"]:
                if "value" in group:
                    value_groups.append(parse_as_list(group["value"]))
                elif "values" in group:
                    value_groups.append(parse_as_list(group["values"]))
                else:
                    current_app.logger.warn("Group %s missing value(s)" % group)
                    return ptus_incomplete()
        else:
            current_app.logger.warn("Request missing value(s) or group.")
            return ptus_incomplete()

        if not contains_empty_items(value_groups):
            kwargs["value_groups"] = value_groups
            return fn(*args, **kwargs)
        else:
            current_app.logger.warn("Request includes empty value(s).")
            return ptus_incomplete()

    return wrapper


def type_accepted(message_type: str):
    """Decorator which specifies that a GET or POST request must specify the specified message type. Example:

        @app.route('/postMeterData')
        @type_accepted('PostMeterDataRequest')
        def post_meter_data():
            return 'Meter data posted'

    The message must specify 'PostMeterDataRequest' as its 'type'.

    :param message_type: The message type.
    """

    def wrapper(fn):
        @wraps(fn)
        @as_json
        def decorated_service(*args, **kwargs):
            form = get_form_from_request(request)
            if form is None:
                current_app.logger.warn(
                    "Unsupported request method for unpacking 'unit' from request."
                )
                return invalid_method(request.method)
            elif "type" not in form:
                current_app.logger.warn("Request is missing message type.")
                return no_message_type()
            elif form["type"] != message_type:
                current_app.logger.warn("Type is not accepted for this endpoint.")
                return invalid_message_type(message_type)
            else:
                return fn(*args, **kwargs)

        return decorated_service

    return wrapper


def units_accepted(*units):
    """Decorator which specifies that a GET or POST request must specify one of the
    specified physical units. Example:

        @app.route('/postMeterData')
        @units_accepted('MW', 'MWh')
        def post_meter_data():
            return 'Meter data posted'

    The message must either specify 'MW' or 'MWh' as the unit.

    :param units: The possible units.
    """

    def wrapper(fn):
        @wraps(fn)
        @as_json
        def decorated_service(*args, **kwargs):
            form = get_form_from_request(request)
            if form is None:
                current_app.logger.warn(
                    "Unsupported request method for unpacking 'unit' from request."
                )
                return invalid_method(request.method)
            elif "unit" not in form:
                current_app.logger.warn("Request is missing unit.")
                return invalid_unit()
            elif form["unit"] not in units:
                current_app.logger.warn("Unit is not accepted.")
                return invalid_unit()
            else:
                kwargs["unit"] = form["unit"]
                return fn(*args, **kwargs)

        return decorated_service

    return wrapper


def usef_roles_accepted(*usef_roles):
    """Decorator which specifies that a user must have at least one of the
    specified USEF roles (or must be an admin). Example:

        @app.route('/postMeterData')
        @roles_accepted('Prosumer', 'MDC')
        def post_meter_data():
            return 'Meter data posted'

    The current user must have either the `Prosumer` role or `MDC` role in
    order to use the service.

    :param usef_roles: The possible roles.
    """

    def wrapper(fn):
        @wraps(fn)
        @as_json
        def decorated_service(*args, **kwargs):
            perm = Permission(*[RoleNeed(role) for role in usef_roles])
            if perm.can() or current_user.has_role("admin"):
                return fn(*args, **kwargs)
            else:
                current_app.logger.warn("User role is not accepted for this service")
                return invalid_sender(
                    [role.name for role in current_user.roles], *usef_roles
                )

        return decorated_service

    return wrapper
