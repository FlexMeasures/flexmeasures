from datetime import datetime, timedelta
from functools import wraps
from typing import List, Tuple, Union, Optional
import re

import isodate
from isodate.isoerror import ISO8601Error
import inflect
from inflection import pluralize
from pandas.tseries.frequencies import to_offset
from flask import request, current_app
from flask_json import as_json
from flask_principal import Permission, RoleNeed
from flask_security import current_user
import marshmallow

from webargs.flaskparser import parser

from flexmeasures.api.common.schemas.times import DurationField
from flexmeasures.api.common.responses import (  # noqa: F401
    required_info_missing,
    invalid_horizon,
    invalid_method,
    invalid_message_type,
    invalid_period,
    unapplicable_resolution,
    invalid_resolution_str,
    conflicting_resolutions,
    invalid_sender,
    invalid_source,
    invalid_timezone,
    invalid_unit,
    no_message_type,
    ptus_incomplete,
    unrecognized_connection_group,
    unrecognized_asset,
)
from flexmeasures.api.common.utils.api_utils import (
    get_form_from_request,
    parse_as_list,
    contains_empty_items,
    upsample_values,
    get_generic_asset,
)
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.config import db
from flexmeasures.data.services.users import get_users
from flexmeasures.utils.time_utils import server_now


p = inflect.engine()


def validate_user_sources(sources: Union[int, str, List[Union[int, str]]]) -> List[int]:
    """Return a list of user source ids given a user id, a role name or a list thereof."""
    sources = (
        sources if isinstance(sources, list) else [sources]
    )  # Make sure sources is a list
    user_source_ids: List[int] = []
    for source in sources:
        if isinstance(source, int):  # Parse as user id
            try:
                user_source_ids.extend(
                    db.session.query(DataSource.id)
                    .filter(DataSource.user_id == source)
                    .one_or_none()
                )
            except TypeError:
                current_app.logger.warning("Could not retrieve data source %s" % source)
                pass
        else:  # Parse as role name
            user_ids = [user.id for user in get_users(source)]
            user_source_ids.extend(
                [
                    params[0]
                    for params in db.session.query(DataSource.id)
                    .filter(DataSource.user_id.in_(user_ids))
                    .all()
                ]
            )
    return list(set(user_source_ids))  # only unique ids


def include_current_user_source_id(source_ids: List[int]) -> List[int]:
    """Includes the source id of the current user."""
    source_ids.extend(
        db.session.query(DataSource.id)
        .filter(DataSource.user_id == current_user.id)
        .one_or_none()
    )
    return list(set(source_ids))  # only unique source ids


def parse_horizon(horizon_str: str) -> Tuple[Optional[timedelta], bool]:
    """
    Validates whether a horizon string represents a valid ISO 8601 (repeating) time interval.

    Examples:

        horizon = "PT6H"
        horizon = "R/PT6H"
        horizon = "-PT10M"

    Returns horizon as timedelta and a boolean indicating whether the repetitive indicator "R/" was used.
    If horizon_str could not be parsed with various methods, then horizon will be None
    """
    # negativity
    neg = False
    if horizon_str[0] == "-":
        neg = True
        horizon_str = horizon_str[1:]

    # repetition-encoding
    is_repetition: bool = False
    if re.search(r"^R\d*/", horizon_str):
        _, horizon_str, *_ = re.split("/", horizon_str)
        is_repetition = True

    # parse
    try:
        horizon: timedelta = isodate.parse_duration(horizon_str)
    except (ISO8601Error, AttributeError):
        return None, is_repetition

    if neg:
        horizon = -horizon
    return horizon, is_repetition


def parse_duration(
    duration_str: str, start: Optional[datetime] = None
) -> Union[timedelta, isodate.Duration, None]:
    """
    Parses the 'duration' string into a Duration object.
    If needed, try deriving the timedelta from the actual time span (e.g. in case duration is 1 year).
    If the string is not a valid ISO 8601 time interval, return None.

    TODO: Deprecate for DurationField.
    """
    try:
        duration = isodate.parse_duration(duration_str)
        if not isinstance(duration, timedelta) and start:
            return (start + duration) - start
        # if not a timedelta, then it's a valid duration (e.g. "P1Y" could be leap year)
        return duration
    except (ISO8601Error, AttributeError):
        return None


def parse_isodate_str(start: str) -> Union[datetime, None]:
    """
    Validates whether the string 'start' is a valid ISO 8601 datetime.
    """
    try:
        return isodate.parse_datetime(start)
    except (ISO8601Error, AttributeError):
        return None


def valid_sensor_units(sensor: str) -> List[str]:
    """
    Returns the accepted units for this sensor.
    """
    if sensor == "temperature":
        return ["°C", "0C"]
    elif sensor == "radiation":
        return ["kW/m²", "kW/m2"]
    elif sensor == "wind_speed":
        return ["m/s"]
    else:
        raise NotImplementedError(
            "Unknown sensor or physical unit, cannot determine valid units."
        )


def optional_duration_accepted(default_duration: timedelta):
    """Decorator which specifies that a GET or POST request accepts an optional duration.
    It parses relevant form data and sets the "duration" keyword param.

    Example:

        @app.route('/getDeviceMessage')
        @optional_duration_accepted(timedelta(hours=6))
        def get_device_message(duration):
            return 'Here is your message'

    The message may specify a duration to overwrite the default duration of 6 hours.
    """

    def wrapper(fn):
        @wraps(fn)
        @as_json
        def decorated_service(*args, **kwargs):
            duration_arg = parser.parse(
                {"duration": DurationField()},
                request,
                location="args_and_json",
                unknown=marshmallow.EXCLUDE,
            )
            if "duration" in duration_arg:
                duration = duration_arg["duration"]
                duration = DurationField.ground_from(
                    duration,
                    kwargs.get("start", kwargs.get("datetime", None)),
                )
                if not duration:  # TODO: deprecate
                    extra_info = "Cannot parse 'duration' value."
                    current_app.logger.warning(extra_info)
                    return invalid_period(extra_info)
                kwargs["duration"] = duration
            else:
                kwargs["duration"] = default_duration
            return fn(*args, **kwargs)

        return decorated_service

    return wrapper


def optional_user_sources_accepted(
    default_source: Union[int, str, List[Union[int, str]]] = None
):
    """Decorator which specifies that a GET or POST request accepts an optional source or list of data sources.
    It parses relevant form data and sets the "user_source_ids" keyword parameter.

    Data originating from the requesting user is included by default.
    That is, user_source_ids always includes the source id of the requesting user.

    Each source should either be a known USEF role name or a user id.
    We'll parse them as a list of source ids.

    Case 1:
    If a request states one or more data sources, then we'll only query those, in addition to the user's own data.
    Default sources specified in the decorator (see example below) are ignored.

    Case 2:
    If a request does not state any data sources, a list of default sources will be used.

        Case 2A:
        Default sources can be specified in the decorator (see example below).

        Case 2B:
        If no default sources are specified in the decorator, all sources are included.

    Example:

        @app.route('/getMeterData')
        @optional_sources_accepted("MDC")
        def get_meter_data(user_source_ids):
            return 'Meter data posted'

    The source ids then include the user's own id,
    and ids of other users that are registered as a Meter Data Company.

    If the message specifies:

    .. code-block:: json

        {
            "sources": ["Prosumer", "ESCo"]
        }

    The source ids then include the user's own id,
    and ids of other users that are registered as a Prosumer and/or Energy Service Company.
    """

    def wrapper(fn):
        @wraps(fn)
        @as_json
        def decorated_service(*args, **kwargs):
            form = get_form_from_request(request)
            if form is None:
                current_app.logger.warning(
                    "Unsupported request method for unpacking 'source' from request."
                )
                return invalid_method(request.method)

            if "source" in form:
                validated_user_source_ids = validate_user_sources(form["source"])
                if None in validated_user_source_ids:
                    return invalid_source(form["source"])
                kwargs["user_source_ids"] = include_current_user_source_id(
                    validated_user_source_ids
                )
            elif default_source is not None:
                kwargs["user_source_ids"] = include_current_user_source_id(
                    validate_user_sources(default_source)
                )
            else:
                kwargs["user_source_ids"] = None

            return fn(*args, **kwargs)

        return decorated_service

    return wrapper


def optional_prior_accepted(ex_post: bool = False, infer_missing: bool = True):
    """Decorator which specifies that a GET or POST request accepts an optional prior.
    It parses relevant form data and sets the "prior" keyword param.

    Interpretation for GET requests:
    -   Denotes "at least before <prior>"
    -   This results in the filter belief_time_window = (None, prior)

    Optionally, an ex_post flag can be passed to the decorator to indicate that only ex-post datetimes are allowed.
    As a useful setting (at least for POST requests), set infer_missing to True to have servers
    (that are not in play mode) derive a prior from the server time.
    """

    def wrapper(fn):
        @wraps(fn)
        @as_json
        def decorated_service(*args, **kwargs):
            form = get_form_from_request(request)
            if form is None:
                current_app.logger.warning(
                    "Unsupported request method for unpacking 'prior' from request."
                )
                return invalid_method(request.method)

            if "prior" in form:
                prior = parse_isodate_str(form["prior"])
                if ex_post is True:
                    start = parse_isodate_str(form["start"])
                    duration = parse_duration(form["duration"], start)
                    # todo: validate start and duration (refactor already duplicate code from period_required and optional_horizon_accepted)
                    knowledge_time = (
                        start + duration
                    )  # todo: take into account knowledge horizon function
                    if prior < knowledge_time:
                        extra_info = "Meter data can only be observed after the fact."
                        return invalid_horizon(extra_info)
            elif (
                infer_missing is True
                and current_app.config.get("FLEXMEASURES_MODE", "") != "play"
            ):
                # A missing prior is inferred by the server (if not in play mode)
                prior = server_now()
            else:
                # Otherwise, a missing prior is fine (a horizon may still be inferred by the server)
                prior = None

            kwargs["prior"] = prior
            return fn(*args, **kwargs)

        return decorated_service

    return wrapper


def optional_horizon_accepted(  # noqa C901
    ex_post: bool = False,
    infer_missing: bool = True,
    accept_repeating_interval: bool = False,
):
    """Decorator which specifies that a GET or POST request accepts an optional horizon.
    The horizon should be in accordance with the ISO 8601 standard.
    It parses relevant form data and sets the "horizon" keyword param (a timedelta).

    Interpretation for GET requests:
    -   Denotes "at least <horizon> before the fact (positive horizon),
        or at most <horizon> after the fact (negative horizon)"
    -   This results in the filter belief_horizon_window = (horizon, None)

    Interpretation for POST requests:
    -   Denotes "at <horizon> before the fact (positive horizon),
        or at <horizon> after the fact (negative horizon)"
    -   this results in the assignment belief_horizon = horizon

    For example:

        @app.route('/postMeterData')
        @optional_horizon_accepted()
        def post_meter_data(horizon):
            return 'Meter data posted'

    :param ex_post:                   if True, only non-positive horizons are allowed.
    :param infer_missing:             if True, servers that are in play mode assume that the belief_horizon of posted
                                      values is 0 hours. This setting is meant to be used for POST requests.
    :param accept_repeating_interval: if True, the "rolling" keyword param is also set
                                      (this was used for POST requests before v2.0)
    """

    def wrapper(fn):
        @wraps(fn)
        @as_json
        def decorated_service(*args, **kwargs):
            form = get_form_from_request(request)
            if form is None:
                current_app.logger.warning(
                    "Unsupported request method for unpacking 'horizon' from request."
                )
                return invalid_method(request.method)

            rolling = True
            if "horizon" in form:
                horizon, rolling = parse_horizon(form["horizon"])
                if horizon is None:
                    current_app.logger.warning("Cannot parse 'horizon' value")
                    return invalid_horizon()
                elif ex_post is True:
                    if horizon > timedelta(hours=0):
                        extra_info = "Meter data must have a zero or negative horizon to indicate observations after the fact."
                        return invalid_horizon(extra_info)
                elif rolling is True and accept_repeating_interval is False:
                    extra_info = (
                        "API versions 2.0 and higher use regular ISO 8601 durations instead of repeating time intervals. "
                        "For example: R/P1D should be replaced by P1D."
                    )
                    return invalid_horizon(extra_info)
            elif (
                infer_missing is True
                and current_app.config.get("FLEXMEASURES_MODE", "") == "play"
            ):
                # A missing horizon is set to zero for servers in play mode
                horizon = timedelta(hours=0)
            elif infer_missing is True and accept_repeating_interval is True:
                extra_info = "Missing horizons are no longer accepted for API versions below v2.0."
                return invalid_horizon(extra_info)
            else:
                # Otherwise, a missing horizon is fine (a prior may still be inferred by the server)
                horizon = None

            kwargs["horizon"] = horizon
            if infer_missing is True and accept_repeating_interval is True:
                kwargs["rolling"] = rolling
            return fn(*args, **kwargs)

        return decorated_service

    return wrapper


def unit_required(fn):
    """Decorator which specifies that a GET or POST request must specify a unit.
    It parses relevant form data and sets the "unit keyword param.
    Example:

        @app.route('/postMeterData')
        @unit_required
        def post_meter_data(unit):
            return 'Meter data posted'

    The message must specify a 'unit'.
    """

    @wraps(fn)
    @as_json
    def wrapper(*args, **kwargs):
        form = get_form_from_request(request)
        if form is None:
            current_app.logger.warning(
                "Unsupported request method for unpacking 'unit' from request."
            )
            return invalid_method(request.method)

        if "unit" in form:
            unit = form["unit"]
        else:
            current_app.logger.warning("Request missing 'unit'.")
            return invalid_unit(quantity=None, units=None)

        kwargs["unit"] = unit
        return fn(*args, **kwargs)

    return wrapper


def period_required(fn):
    """Decorator which specifies that a GET or POST request must specify a time period (by start and duration).
    It parses relevant form data and sets the "start" and "duration" keyword params.
    Example:

        @app.route('/postMeterData')
        @period_required
        def post_meter_data(period):
            return 'Meter data posted'

    The message must specify a 'start' and a 'duration' in accordance with the ISO 8601 standard.
    This decorator should not be used together with optional_duration_accepted.
    """

    @wraps(fn)
    @as_json
    def wrapper(*args, **kwargs):
        form = get_form_from_request(request)
        if form is None:
            current_app.logger.warning(
                "Unsupported request method for unpacking 'start' and 'duration' from request."
            )
            return invalid_method(request.method)

        if "start" in form:
            start = parse_isodate_str(form["start"])
            if not start:
                current_app.logger.warning("Cannot parse 'start' value")
                return invalid_period()
            if start.tzinfo is None:
                current_app.logger.warning("Cannot parse timezone of 'start' value")
                return invalid_timezone(
                    "Start time should explicitly state a timezone."
                )
        else:
            current_app.logger.warning("Request missing 'start'.")
            return invalid_period()
        kwargs["start"] = start
        if "duration" in form:
            duration = parse_duration(form["duration"], start)
            if not duration:
                current_app.logger.warning("Cannot parse 'duration' value")
                return invalid_period()
        else:
            current_app.logger.warning("Request missing 'duration'.")
            return invalid_period()
        kwargs["duration"] = duration
        return fn(*args, **kwargs)

    return wrapper


def assets_required(
    generic_asset_type_name: str, plural_name: str = None, groups_name="groups"
):
    """Decorator which specifies that a GET or POST request must specify one or more assets.
    It parses relevant form data and sets the "generic_asset_name_groups" keyword param.
    Example:

        @app.route('/postMeterData')
        @assets_required("connection", plural_name="connections")
        def post_meter_data(generic_asset_name_groups):
            return 'Meter data posted'

    Given this example, the message must specify one or more assets as "connections".
    If that is the case, then the assets are passed to the function as generic_asset_name_groups.

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
                current_app.logger.warning(
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
                        current_app.logger.warning(
                            "Group %s missing %s" % (group, plural_name)
                        )
                        return unrecognized_connection_group()
            else:
                current_app.logger.warning("Request missing %s or group." % plural_name)
                return unrecognized_connection_group()

            if not contains_empty_items(generic_asset_name_groups):
                kwargs["generic_asset_name_groups"] = generic_asset_name_groups
                return fn(*args, **kwargs)
            else:
                current_app.logger.warning("Request includes empty %s." % plural_name)
                return unrecognized_connection_group()

        return decorated_service

    return wrapper


def values_required(fn):
    """Decorator which specifies that a GET or POST request must specify one or more values.
    It parses relevant form data and sets the "value_groups" keyword param.
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
            current_app.logger.warning(
                "Unsupported request method for unpacking 'values' from request."
            )
            return invalid_method(request.method)

        if "value" in form:
            value_groups = [parse_as_list(form["value"], of_type=float)]
        elif "values" in form:
            value_groups = [parse_as_list(form["values"], of_type=float)]
        elif "groups" in form:
            value_groups = []
            for group in form["groups"]:
                if "value" in group:
                    value_groups.append(parse_as_list(group["value"], of_type=float))
                elif "values" in group:
                    value_groups.append(parse_as_list(group["values"], of_type=float))
                else:
                    current_app.logger.warning("Group %s missing value(s)" % group)
                    return ptus_incomplete()
        else:
            current_app.logger.warning("Request missing value(s) or group.")
            return ptus_incomplete()

        if not contains_empty_items(value_groups):
            kwargs["value_groups"] = value_groups
            return fn(*args, **kwargs)
        else:
            extra_info = "Request includes empty or ill-formatted value(s)."
            current_app.logger.warning(extra_info)
            return ptus_incomplete(extra_info)

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
                current_app.logger.warning(
                    "Unsupported request method for unpacking 'type' from request."
                )
                return invalid_method(request.method)
            elif "type" not in form:
                current_app.logger.warning("Request is missing message type.")
                return no_message_type()
            elif form["type"] != message_type:
                current_app.logger.warning("Type is not accepted for this endpoint.")
                return invalid_message_type(message_type)
            else:
                return fn(*args, **kwargs)

        return decorated_service

    return wrapper


def units_accepted(quantity: str, *units: str):
    """Decorator which specifies that a GET or POST request must specify one of the
    specified physical units. First parameter specifies the physical or economical quantity.
    It parses relevant form data and sets the "unit" keyword param.
    Example:

        @app.route('/postMeterData')
        @units_accepted("power", 'MW', 'MWh')
        def post_meter_data(unit):
            return 'Meter data posted'

    The message must either specify 'MW' or 'MWh' as the unit.

    :param quantity: The physical or economic quantity
    :param units: The possible units.
    """

    def wrapper(fn):
        @wraps(fn)
        @as_json
        def decorated_service(*args, **kwargs):
            form = get_form_from_request(request)
            if form is None:
                current_app.logger.warning(
                    "Unsupported request method for unpacking 'unit' from request."
                )
                return invalid_method(request.method)
            elif "unit" not in form:
                current_app.logger.warning("Request is missing unit.")
                return invalid_unit(quantity, units)
            elif form["unit"] not in units:
                current_app.logger.warning(
                    "Unit %s is not accepted as one of %s." % (form["unit"], units)
                )
                return invalid_unit(quantity, units)
            else:
                kwargs["unit"] = form["unit"]
                return fn(*args, **kwargs)

        return decorated_service

    return wrapper


def post_data_checked_for_required_resolution(entity_type):  # noqa: C901
    """Decorator which checks that a POST request receives time series data with the event resolutions
    required by the sensor (asset). It sets the "resolution" keyword argument.
    If the resolution in the data is a multiple of the asset resolution, values are upsampled to the asset resolution.
    Finally, this decorator also checks if all assets have the same event_resolution and complains otherwise.

    The resolution of the data is inferred from the duration and the number of values.
    Therefore, the decorator should follow after the values_required, period_required and assets_required decorators.
    Example:

        @app.route('/postMeterData')
        @values_required
        @period_required
        @assets_required("connection")
        @post_data_checked_for_required_resolution("connection")
        def post_meter_data(value_groups, start, duration, generic_asset_name_groups, resolution)
            return 'Meter data posted'
    """

    def wrapper(fn):
        @wraps(fn)
        @as_json
        def decorated_service(*args, **kwargs):
            form = get_form_from_request(request)
            if form is None:
                current_app.logger.warning(
                    "Unsupported request method for inferring resolution from request."
                )
                return invalid_method(request.method)

            if not all(
                key in kwargs
                for key in [
                    "value_groups",
                    "start",
                    "duration",
                ]
            ):
                current_app.logger.warning("Could not infer resolution.")
                fields = ("values", "start", "duration")
                return required_info_missing(fields, "Resolution cannot be inferred.")
            if "generic_asset_name_groups" not in kwargs:
                return required_info_missing(
                    (entity_type),
                    "Required resolution cannot be found without asset info.",
                )

            # Calculating (inferring) the resolution in the POSTed data
            inferred_resolution = (
                (kwargs["start"] + kwargs["duration"]) - kwargs["start"]
            ) / len(kwargs["value_groups"][0])

            # Finding the required resolution for assets affected in this request
            required_resolution = None
            last_asset = None
            for asset_group in kwargs["generic_asset_name_groups"]:
                for asset_descriptor in asset_group:
                    # Getting the asset
                    generic_asset = get_generic_asset(asset_descriptor, entity_type)
                    if generic_asset is None:
                        return unrecognized_asset(
                            f"Failed to look up asset by {asset_descriptor}"
                        )
                    # Complain if assets don't all require the same resolution
                    if (
                        required_resolution is not None
                        and generic_asset.event_resolution != required_resolution
                    ):
                        return conflicting_resolutions(
                            f"Cannot send data for both {generic_asset} and {last_asset}."
                        )
                    # Setting the resolution & remembering last looked-at asset
                    required_resolution = generic_asset.event_resolution
                    last_asset = generic_asset

            # if inferred resolution is a multiple from required_solution, we can upsample_values
            if inferred_resolution % required_resolution == timedelta(hours=0):
                for i in range(len(kwargs["value_groups"])):
                    kwargs["value_groups"][i] = upsample_values(
                        kwargs["value_groups"][i],
                        from_resolution=inferred_resolution,
                        to_resolution=required_resolution,
                    )
                inferred_resolution = required_resolution

            if inferred_resolution != required_resolution:
                current_app.logger.warning(
                    f"Resolution {inferred_resolution} is not accepted. We require {required_resolution}."
                )
                return unapplicable_resolution(
                    isodate.duration_isoformat(required_resolution)
                )
            else:
                kwargs["resolution"] = inferred_resolution
                return fn(*args, **kwargs)

        return decorated_service

    return wrapper


def get_data_downsampling_allowed(entity_type):
    """Decorator which allows downsampling of data which a GET request returns.
    It checks for a form parameter "resolution".
    If that is given and is a multiple of the asset's event_resolution,
    downsampling is performed on the data. This is done by setting the "resolution"
    keyword parameter, which is obeyed by collect_time_series_data and used
    in resampling.

    The original resolution of the data is the event_resolution of the asset.
    Therefore, the decorator should follow after the assets_required decorator.

    Example:

        @app.route('/getMeterData')
        @assets_required("connection")
        @get_data_downsampling_allowed("connection")
        def get_meter_data(generic_asset_name_groups, resolution):
            return data

    """

    def wrapper(fn):
        @wraps(fn)
        @as_json
        def decorated_service(*args, **kwargs):
            kwargs[
                "resolution"
            ] = None  # using this decorator means you can expect this attribute, None means default
            form = get_form_from_request(request)
            if form is None:
                current_app.logger.warning(
                    "Unsupported request method for unpacking 'resolution' from request."
                )
                return invalid_method(request.method)

            if "resolution" in form and form["resolution"]:
                ds_resolution = parse_duration(form["resolution"])
                if ds_resolution is None:
                    return invalid_resolution_str(form["resolution"])
                # Check if the resolution can be applied to all assets (if it is a multiple
                # of the event_resolution(s) and thus downsampling is possible)
                for asset_group in kwargs["generic_asset_name_groups"]:
                    for asset_descriptor in asset_group:
                        generic_asset = get_generic_asset(asset_descriptor, entity_type)
                        if generic_asset is None:
                            return unrecognized_asset()
                        asset_resolution = generic_asset.event_resolution
                        if ds_resolution % asset_resolution != timedelta(minutes=0):
                            return unapplicable_resolution(
                                f"{isodate.duration_isoformat(asset_resolution)} or a multiple hereof."
                            )
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
    And finally, users with the anonymous user role are never accepted.

    :param usef_roles: The possible roles.
    """

    def wrapper(fn):
        @wraps(fn)
        @as_json
        def decorated_service(*args, **kwargs):
            perm = Permission(*[RoleNeed(role) for role in usef_roles])
            if current_user.has_role(
                "anonymous"
            ):  # TODO: this role needs to go, we should not mix permissive and restrictive roles
                current_app.logger.warning(
                    "Anonymous user is not accepted for this service"
                )
                return invalid_sender("anonymous user", "non-anonymous user")
            elif perm.can() or current_user.has_role("admin"):
                return fn(*args, **kwargs)
            else:
                current_app.logger.warning(
                    "User does not have necessary authorization for this service"
                )
                return invalid_sender(
                    [role.name for role in current_user.roles], *usef_roles
                )

        return decorated_service

    return wrapper
