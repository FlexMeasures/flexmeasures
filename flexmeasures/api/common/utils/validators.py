from __future__ import annotations

from datetime import datetime, timedelta
from functools import wraps
import re

import isodate
from isodate.isoerror import ISO8601Error
from flask import request, current_app
from flask_json import as_json
import marshmallow

from webargs.flaskparser import parser

from flexmeasures.data.schemas.times import DurationField
from flexmeasures.api.common.responses import (  # noqa: F401
    required_info_missing,
    invalid_horizon,
    invalid_method,
    invalid_message_type,
    invalid_period,
    unapplicable_resolution,
    invalid_resolution_str,
    conflicting_resolutions,
    invalid_source,
    invalid_timezone,
    invalid_unit,
    no_message_type,
    ptus_incomplete,
    unrecognized_connection_group,
    unrecognized_asset,
)

"""
This module has validators used by API endpoints <= 2.0 to describe
acceptable parameters.
We aim to make this module obsolete by using Marshmallow.
Marshmallow is a better format to describe valid data.
There is some actual logic in here, which we still need. It can usually be ported to Marshmallow validators.
"""


def parse_horizon(horizon_str: str) -> tuple[timedelta | None, bool]:
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
    duration_str: str, start: datetime | None = None
) -> timedelta | isodate.Duration | None:
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
