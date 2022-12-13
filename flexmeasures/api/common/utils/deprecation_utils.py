"""
Business logic.  Kept separate in case the project
becomes larger for some reason in the future.
"""
from __future__ import absolute_import
from __future__ import annotations
from __future__ import division
from __future__ import print_function

from flask import current_app, request, Blueprint, Response
from flask_security.core import current_user
import pandas as pd

from flexmeasures.utils.time_utils import to_http_time


def deprecate_blueprint(
    blueprint: Blueprint,
    deprecation_date: pd.Timestamp | str | None = None,
    deprecation_link: str | None = None,
    sunset_date: pd.Timestamp | str | None = None,
    sunset_link: str | None = None,
):
    """Deprecates every route on a blueprint by adding the "Deprecation" header with a deprecation date.

    >>> from flask import Flask, Blueprint
    >>> app = Flask('some_app')
    >>> deprecated_bp = Blueprint('API version 1', 'v1_bp')
    >>> app.register_blueprint(deprecated_bp, url_prefix='/v1')
    >>> deprecate_blueprint(
            deprecated_bp,
            deprecation_date="2022-12-14",
            deprecation_link="https://flexmeasures.readthedocs.org/some-deprecation-notice",
            sunset_date="2023-02-01",
            sunset_link="https://flexmeasures.readthedocs.org/some-sunset-notice",
        )

    :param blueprint:        The blueprint to be deprecated
    :param deprecation_date: date indicating when the API endpoint was deprecated, used for the "Deprecation" header
                             if no date is given, defaults to "true"
                             see https://datatracker.ietf.org/doc/html/draft-ietf-httpapi-deprecation-header#section-2-1
    :param deprecation_link: url providing more information about the deprecation
    :param sunset_date:      date indicating when the API endpoint is likely to become unresponsive
    :param sunset_link:      url providing more information about the sunset

    References
    ----------
    - Deprecation field: https://datatracker.ietf.org/doc/html/draft-ietf-httpapi-deprecation-header
    - Sunset field: https://www.rfc-editor.org/rfc/rfc8594
    """
    if deprecation_date:
        deprecation = to_http_time(pd.Timestamp(deprecation_date) - pd.Timedelta("1s"))
    else:
        deprecation = "true"
    if sunset_date:
        sunset = to_http_time(pd.Timestamp(sunset_date) - pd.Timedelta("1s"))

    def _after_request_handler(response: Response) -> Response:
        return _add_headers(
            response,
            deprecation,
            deprecation_link,
            sunset,
            sunset_link,
        )

    blueprint.after_request(_after_request_handler)


def _add_headers(
    response: Response,
    deprecation: str,
    deprecation_link: str | None,
    sunset: str | None,
    sunset_link: str | None,
) -> Response:
    response.headers["Deprecation"] = deprecation
    if sunset:
        response.headers["Sunset"] = sunset
    if deprecation_link:
        response = _add_link(response, deprecation_link, "deprecation")
    if sunset_link:
        response = _add_link(response, sunset_link, "sunset")
    current_app.logger.warning(
        f"Deprecated endpoint {request.endpoint} called by {current_user}"
    )
    return response


def _add_link(response: Response, link: str, rel: str) -> Response:
    link_text = f'<{link}>; rel="{rel}"; type="text/html"'
    if response.headers.get("Link"):
        response.headers["Link"] += f", {link_text}"
    else:
        response.headers["Link"] = link_text
    return response
