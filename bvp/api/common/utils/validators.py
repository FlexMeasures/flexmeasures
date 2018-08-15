from datetime import datetime, timedelta
import re
from functools import wraps
from typing import List, Tuple, Union

import isodate
from isodate.isoerror import ISO8601Error
from inflection import pluralize
from pandas.tseries.frequencies import to_offset
from flask import request, current_app
from flask_json import as_json
from flask_principal import Permission, RoleNeed
from flask_security import current_user

from bvp.api.common.responses import (  # noqa: F401
    invalid_domain,
    invalid_horizon,
    invalid_method,
    invalid_message_type,
    invalid_period,
    invalid_resolution,
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
    zip_dic,
)
from bvp.data.models.data_sources import DataSource
from bvp.data.config import db
from bvp.data.services.users import get_users
from bvp.utils.time_utils import bvp_now


def validate_sources(sources: Union[int, str, List[Union[int, str]]]) -> List[int]:
    """Return a list of source ids given a user id, a role name or a list thereof.
    Always include the user id of the current user."""
    sources = (
        sources if isinstance(sources, list) else [sources]
    )  # Make sure sources is a list
    source_ids = []
    for source in sources:
        if isinstance(source, int):  # Parse as user id
            try:
                source_ids.extend(
                    db.session.query(DataSource.id)
                    .filter(DataSource.user_id == source)
                    .one_or_none()
                )
            except TypeError:
                current_app.logger.warn("Could not retrieve data source %s" % source)
                pass
        else:  # Parse as role name
            user_ids = [user.id for user in get_users(source)]
            source_ids.extend(
                db.session.query(DataSource.id)
                .filter(DataSource.user_id.in_(user_ids))
                .all()
            )
    source_ids = [
        source_id if isinstance(source_id, int) else int(source_id[0])
        for source_id in source_ids
    ]
    source_ids.extend(
        db.session.query(DataSource.id)
        .filter(DataSource.user_id == current_user.id)
        .one_or_none()
    )
    return list(set(source_ids))  # only unique source ids


def validate_horizon(horizon: str) -> Union[Tuple[timedelta, bool], Tuple[None, None]]:
    """
    Validates whether the string 'horizon' is a valid ISO 8601 (repeating) time interval.

    Examples:

        horizon = "PT6H"
        horizon = "R/PT6H"
        horizon = "-PT10M"

    """
    if horizon[0] == "-":
        neg = True
        horizon = horizon[1:]
    else:
        neg = False
    if re.search("^R\d*/", horizon):
        _, horizon, *_ = re.split("/", horizon)
        rep = True
    else:
        rep = False
    try:
        horizon = isodate.parse_duration(horizon)
    except ISO8601Error:
        return None, None
    if neg:
        horizon = -horizon
    return horizon, rep


def validate_duration(duration: str) -> Union[timedelta, None]:
    """
    Validates whether the string 'duration' is a valid ISO 8601 time interval.
    """
    try:
        return isodate.parse_duration(duration)
    except ISO8601Error:
        return None


def validate_start(start: str) -> Union[datetime, None]:
    """
    Validates whether the string 'start' is a valid ISO 8601 datetime.
    """
    try:
        return isodate.parse_datetime(start)
    except ISO8601Error:
        return None


def validate_entity_address(generic_asset_name: str, entity_type: str) -> dict:
    """
    Validates whether the generic asset name is a valid type 1 USEF entity address.
    That is, it must follow the EA1 addressing scheme recommended by USEF.

    For example:

        connection = ea1.2018-06.localhost:5000:40:30
        connection = ea1.2018-06.com.a1-bvp:<owner-id>:<asset-id>'
        sensor = ea1.2018-06.com.a1-bvp:temperature:52:73.0

    """
    if entity_type == "connection":
        match = re.search(
            "^"
            "((?P<scheme>.+)\.)*"
            "((?P<naming_authority>\d{4}-\d{2}\..+):(?=.+:))*"  # scheme, naming authority and owner id are optional
            "((?P<owner_id>\d+):(?=.+:{0}))*"
            "(?P<asset_id>\d+)"
            "$",
            generic_asset_name,
        )
        if match:
            value_types = {
                "scheme": str,
                "naming_authority": str,
                "owner_id": int,
                "asset_id": int,
            }
            return {
                k: v_type(v) if v is not None else v
                for k, v, v_type in zip_dic(match.groupdict(), value_types)
            }

    elif entity_type == "sensor":
        match = re.search(
            "^"
            "(?P<scheme>.+)"
            "\."
            "(?P<naming_authority>\d{4}-\d{2}\..+)"
            ":"
            "(?=[a-zA-Z])(?P<weather_sensor_type_name>[\w]+)"  # should start with at least one letter
            ":"
            "(?P<latitude>\d+(\.\d+)?)"
            ":"
            "(?P<longitude>\d+(\.\d+)?)"
            "$",
            generic_asset_name,
        )
        if match:
            value_types = {
                "scheme": str,
                "naming_authority": str,
                "weather_sensor_type_name": str,
                "latitude": float,
                "longitude": float,
            }
            return {
                k: v_type(v) for k, v, v_type in zip_dic(match.groupdict(), value_types)
            }
    elif entity_type == "market":
        match = re.search(
            "^"
            "(?P<scheme>.+)"
            "\."
            "(?P<naming_authority>\d{4}-\d{2}\..+)"
            ":"
            "(?=[a-zA-Z])(?P<market_name>[\w]+)"  # should start with at least one letter
            "$",
            generic_asset_name,
        )
        if match:
            value_types = {"scheme": str, "naming_authority": str, "market_name": str}
            return {
                k: v_type(v) for k, v, v_type in zip_dic(match.groupdict(), value_types)
            }


def optional_sources_accepted(
    preferred_source: Union[int, str, List[Union[int, str]]] = None
):
    """Decorator which specifies that a GET or POST request accepts an optional source or list of data sources.
    Each source should either be a known USEF role name or a user id.
    We'll parse them as a source id or list of source ids.
    If a requests states one or more data sources, then we'll only query those (no fallback sources).
    However, if one or more preferred data sources are already specified in the decorator, we'll query those instead,
    and if a request states one or more data sources, then we'll only query those as a fallback in case the preferred
    sources don't have any data to give.
    Data originating from the requesting user is always included.
    Example:

        @app.route('/getMeterData')
        @optional_sources_accepted("MDC")
        def get_meter_data(preferred_source_ids, fallback_source_ids):
            return 'Meter data posted'

    The preferred source ids will be those of users that are registered as a meter data company.
    If the message specifies:

    .. code-block:: json

        {
            "sources": ["Prosumer", "ESCo"]
        }

    and the MDC has no data available yet, we'll also query data provided by Prosumers and ESCos.
    If no "source" is specified, we won't query for any other data than from MDCs.
    """

    def wrapper(fn):
        @wraps(fn)
        @as_json
        def decorated_service(*args, **kwargs):
            form = get_form_from_request(request)
            if form is None:
                current_app.logger.warn(
                    "Unsupported request method for unpacking 'source' from request."
                )
                return invalid_method(request.method)

            unknown_sources = False
            if "source" in form:
                validated_sources = validate_sources(form["source"])
                if None in validated_sources:
                    unknown_sources = True
                if preferred_source:
                    preferred_source_ids = validate_sources(preferred_source)
                    fallback_source_ids = validated_sources
                else:
                    preferred_source_ids = validated_sources
                    fallback_source_ids = -1
            else:
                preferred_source_ids = validate_sources(preferred_source)
                fallback_source_ids = -1

            kwargs["preferred_source_ids"] = preferred_source_ids
            kwargs["fallback_source_ids"] = fallback_source_ids

            response = fn(*args, **kwargs)
            if unknown_sources:
                # preferred_source_ids.index(None)  # Todo: improve warning message by referencing the ones that could not be found.
                response["message"].append(" Warning: some data sources are unknown.")
                return response
            else:
                return response

        return decorated_service

    return wrapper


def optional_horizon_accepted(ex_post: bool = False):
    """Decorator which specifies that a GET or POST request accepts an optional horizon. If no horizon is specified,
    the horizon is determined by the server based on when the API endpoint was called.
    Optionally, an ex_post flag can be passed to the decorator to indicate that only negative horizons are allowed.
    Example:

        @app.route('/postMeterData')
        @optional_horizon_accepted()
        def post_meter_data(horizon):
            return 'Meter data posted'

    If the message specifies a "horizon", it should be in accordance with the ISO 8601 standard.
    If no "horizon" is specified, it is determined by the server.
    """

    def wrapper(fn):
        @wraps(fn)
        @as_json
        def decorated_service(*args, **kwargs):
            form = get_form_from_request(request)
            if form is None:
                current_app.logger.warn(
                    "Unsupported request method for unpacking 'horizon' from request."
                )
                return invalid_method(request.method)

            if "horizon" in form:
                horizon, rolling = validate_horizon(form["horizon"])
                if horizon is None:
                    current_app.logger.warn("Cannot parse 'horizon' value")
                    return invalid_horizon()
                elif ex_post is True:
                    if horizon > timedelta(hours=0):
                        extra_info = "Meter data must have a negative horizon to indicate observations after the fact."
                        return invalid_horizon(extra_info)
            elif "start" in form and "duration" in form:
                start = validate_start(form["start"])
                duration = validate_duration(form["duration"])
                if not start:
                    extra_info = "Cannot parse 'start' value."
                    current_app.logger.warn(extra_info)
                    return invalid_period(extra_info)
                if start.tzinfo is None:
                    current_app.logger.warn("Cannot parse timezone of 'start' value")
                    return invalid_timezone()
                if not duration:
                    extra_info = "Cannot parse 'duration' value."
                    current_app.logger.warn(extra_info)
                    return invalid_period(extra_info)
                horizon = start + duration - bvp_now()
                rolling = False
            else:
                current_app.logger.warn(
                    "Request missing both 'horizon', 'start' and 'duration'."
                )
                extra_info = "Specify a 'horizon' value, or 'start' and 'duration' values so that the horizon can be inferred."
                return invalid_horizon(extra_info)

            kwargs["horizon"] = horizon
            kwargs["rolling"] = rolling
            return fn(*args, **kwargs)

        return decorated_service

    return wrapper


def period_required(fn):
    """Decorator which specifies that a GET or POST request must specify a time period.
    Example:

        @app.route('/postMeterData')
        @period_required
        def post_meter_data(period):
            return 'Meter data posted'

    The message must specify a 'start' and a 'duration' in accordance with the ISO 8601 standard.
    """

    @wraps(fn)
    @as_json
    def wrapper(*args, **kwargs):
        form = get_form_from_request(request)
        if form is None:
            current_app.logger.warn(
                "Unsupported request method for unpacking 'start' and 'duration' from request."
            )
            return invalid_method(request.method)

        if "start" in form:
            start = validate_start(form["start"])
            if not start:
                current_app.logger.warn("Cannot parse 'start' value")
                return invalid_period()
            if start.tzinfo is None:
                current_app.logger.warn("Cannot parse timezone of 'start' value")
                return invalid_timezone()
        else:
            current_app.logger.warn("Request missing 'start'.")
            return invalid_period()
        if "duration" in form:
            duration = validate_duration(form["duration"])
            if not duration:
                current_app.logger.warn("Cannot parse 'duration' value")
                return invalid_period()
        else:
            current_app.logger.warn("Request missing 'duration'.")
            return invalid_period()

        kwargs["start"] = start
        kwargs["duration"] = duration
        return fn(*args, **kwargs)

    return wrapper


def assets_required(
    generic_asset_type_name: str, plural_name: str = None, groups_name="groups"
):
    """Decorator which specifies that a GET or POST request must specify one or more assets.
    Example:

        @app.route('/postMeterData')
        @assets_required("connection", plural_name="connections")
        def post_meter_data(generic_asset_name_groups):
            return 'Meter data posted'

    The message must specify one or more connections. If that is the case, then the connections are passed to the
    function as generic_asset_name_groups.

    Connections can be listed in one of the following ways:
    - value of 'connection' key (for a single asset)
    - values of 'connections' key (for multiple assets that have the same timeseries data)
    - values of the 'connection' and/or 'connections' keys listed under the 'groups' key
      (for multiple assets with different timeseries data)
    """
    if plural_name is None:
        plural_name = pluralize(generic_asset_type_name)

    def wrapper(fn):
        @wraps(fn)
        @as_json
        def decorated_service(*args, **kwargs):
            form = get_form_from_request(request)
            if form is None:
                current_app.logger.warn(
                    "Unsupported request method for unpacking '%s' from request."
                    % plural_name
                )
                return invalid_method(request.method)

            if generic_asset_type_name in form:
                generic_asset_name_groups = [
                    parse_as_list(form[generic_asset_type_name])
                ]
            elif plural_name in form:
                generic_asset_name_groups = [parse_as_list(form[plural_name])]
            elif groups_name in form:
                generic_asset_name_groups = []
                for group in form["groups"]:
                    if generic_asset_type_name in group:
                        generic_asset_name_groups.append(
                            parse_as_list(group[generic_asset_type_name])
                        )
                    elif plural_name in group:
                        generic_asset_name_groups.append(
                            parse_as_list(group[plural_name])
                        )
                    else:
                        current_app.logger.warn(
                            "Group %s missing %s" % (group, plural_name)
                        )
                        return unrecognized_connection_group()
            else:
                current_app.logger.warn("Request missing %s or group." % plural_name)
                return unrecognized_connection_group()

            if not contains_empty_items(generic_asset_name_groups):
                kwargs["generic_asset_name_groups"] = generic_asset_name_groups
                return fn(*args, **kwargs)
            else:
                current_app.logger.warn("Request includes empty %s." % plural_name)
                return unrecognized_connection_group()

        return decorated_service

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
        def post_meter_data(unit):
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
                return invalid_unit(units)
            elif form["unit"] not in units:
                current_app.logger.warn("Unit is not accepted.")
                return invalid_unit(units)
            else:
                kwargs["unit"] = form["unit"]
                return fn(*args, **kwargs)

        return decorated_service

    return wrapper


def resolutions_accepted(*resolutions):
    """Decorator which specifies that a GET or POST request accepts one of the specified time resolutions.
    The resolution is inferred from the duration and the number of values.
    Therefore, the decorator should follow after the values_required and the period_required decorators.
    Example:

        @app.route('/postMeterData')
        @values_required
        @period_required
        @resolutions_accepted(timedelta(minutes=15), timedelta(hours=1))
        def post_meter_data(value_groups, start, duration):
            return 'Meter data posted'

    The resolution inferred from the message must be 15 minutes or an hour.

    :param resolutions: The possible resolutions.
    """

    def wrapper(fn):
        @wraps(fn)
        @as_json
        def decorated_service(*args, **kwargs):
            form = get_form_from_request(request)
            if form is None:
                current_app.logger.warn(
                    "Unsupported request method for inferring resolution from request."
                )
                return invalid_method(request.method)

            if "value_groups" in kwargs and "duration" in kwargs:
                resolution = kwargs["duration"] / len(kwargs["value_groups"][0])
                if resolution not in resolutions:
                    current_app.logger.warn("Resolution is not accepted.")
                    return invalid_resolution()
                else:
                    return fn(*args, **kwargs)
            else:
                current_app.logger.warn("Could not infer resolution.")
                extra_info = "Specify some 'values' and a 'duration' so that the resolution can be inferred."
                return invalid_resolution(extra_info)

        return decorated_service

    return wrapper


def optional_resolutions_accepted(*resolutions):
    """Decorator which specifies that a GET or POST request accepts one of the
    specified time resolutions. Example:

        @app.route('/postMeterData')
        @optional_resolutions_accepted('PT15M', 'PT1H')
        def post_meter_data(resolution):
            return 'Meter data posted'

    The message must either specify 'PT15M' or 'PT1H' as the resolution, or no resolution.

    :param resolutions: The possible resolutions.
    """

    def wrapper(fn):
        @wraps(fn)
        @as_json
        def decorated_service(*args, **kwargs):
            form = get_form_from_request(request)
            if form is None:
                current_app.logger.warn(
                    "Unsupported request method for unpacking 'resolution' from request."
                )
                return invalid_method(request.method)

            elif "resolution" not in form:
                kwargs[
                    "resolution"
                ] = "15T"  # Todo: should be decided based on available data
                return fn(*args, **kwargs)
            elif form["resolution"] not in resolutions:
                current_app.logger.warn("Resolution is not accepted.")
                return invalid_resolution()
            else:
                kwargs["resolution"] = to_offset(
                    isodate.parse_duration(form["resolution"])
                ).freqstr  # Convert ISO period string to pandas frequency string
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
