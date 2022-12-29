from __future__ import annotations

from flask import current_app, request, Blueprint, Response, after_this_request
from flask_security.core import current_user
import pandas as pd

from flexmeasures.utils.time_utils import to_http_time


def deprecate_fields(
    fields: str | list[str],
    deprecation_date: pd.Timestamp | str | None = None,
    deprecation_link: str | None = None,
    sunset_date: pd.Timestamp | str | None = None,
    sunset_link: str | None = None,
):
    """Deprecates a field (or fields) on a route by adding the "Deprecation" header with a deprecation date.

    Also logs a warning when a deprecated field is used.

    >>> from flask_classful import route
    >>> @route("/item/", methods=["POST"])
        @use_kwargs(
            {
                "color": ColorField,
                "length": LengthField,
            }
        )
        def post_item(color, length):
            deprecate_field(
                "color",
                deprecation_date="2022-12-14",
                deprecation_link="https://flexmeasures.readthedocs.io/some-deprecation-notice",
                sunset_date="2023-02-01",
                sunset_link="https://flexmeasures.readthedocs.io/some-sunset-notice",
            )

    :param fields:           The fields (as a list of strings) to be deprecated
    :param deprecation_date: date indicating when the field was deprecated, used for the "Deprecation" header
                             if no date is given, defaults to "true"
                             see https://datatracker.ietf.org/doc/html/draft-ietf-httpapi-deprecation-header#section-2-1
    :param deprecation_link: url providing more information about the deprecation
    :param sunset_date:      date indicating when the field is likely to become unresponsive
    :param sunset_link:      url providing more information about the sunset

    References
    ----------
    - Deprecation header: https://datatracker.ietf.org/doc/html/draft-ietf-httpapi-deprecation-header
    - Sunset header: https://www.rfc-editor.org/rfc/rfc8594
    """
    if not isinstance(fields, list):
        fields = [fields]
    deprecation, sunset = _format_deprecation_and_sunset(deprecation_date, sunset_date)

    @after_this_request
    def _after_request_handler(response: Response) -> Response:
        deprecated_fields_used = set(fields) & set(
            request.json.keys()
        )  # sets intersect

        # If any deprecated field is used, log a warning and add deprecation and sunset headers
        if deprecated_fields_used:
            current_app.logger.warning(
                f"Endpoint {request.endpoint} called by {current_user} with deprecated fields: {deprecated_fields_used}"
            )
            return _add_headers(
                response,
                deprecation,
                deprecation_link,
                sunset,
                sunset_link,
            )
        return response


def deprecate_blueprint(
    blueprint: Blueprint,
    deprecation_date: pd.Timestamp | str | None = None,
    deprecation_link: str | None = None,
    sunset_date: pd.Timestamp | str | None = None,
    sunset_link: str | None = None,
):
    """Deprecates every route on a blueprint by adding the "Deprecation" header with a deprecation date.

    Also logs a warning when a deprecated endpoint is called.

    >>> from flask import Flask, Blueprint
    >>> app = Flask('some_app')
    >>> deprecated_bp = Blueprint('API version 1', 'v1_bp')
    >>> app.register_blueprint(deprecated_bp, url_prefix='/v1')
    >>> deprecate_blueprint(
            deprecated_bp,
            deprecation_date="2022-12-14",
            deprecation_link="https://flexmeasures.readthedocs.io/some-deprecation-notice",
            sunset_date="2023-02-01",
            sunset_link="https://flexmeasures.readthedocs.io/some-sunset-notice",
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
    - Deprecation header: https://datatracker.ietf.org/doc/html/draft-ietf-httpapi-deprecation-header
    - Sunset header: https://www.rfc-editor.org/rfc/rfc8594
    """
    deprecation, sunset = _format_deprecation_and_sunset(deprecation_date, sunset_date)

    def _after_request_handler(response: Response) -> Response:
        current_app.logger.warning(
            f"Deprecated endpoint {request.endpoint} called by {current_user}"
        )
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
    response.headers.extend({"Deprecation": deprecation})
    if deprecation_link:
        response = _add_link(response, deprecation_link, "deprecation")
    if sunset:
        response.headers.extend({"Sunset": sunset})
    if sunset_link:
        response = _add_link(response, sunset_link, "sunset")
    return response


def _add_link(response: Response, link: str, rel: str) -> Response:
    link_text = f'<{link}>; rel="{rel}"; type="text/html"'
    response.headers.extend({"Link": link_text})
    return response


def _format_deprecation_and_sunset(deprecation_date, sunset_date):
    if deprecation_date:
        deprecation = to_http_time(pd.Timestamp(deprecation_date) - pd.Timedelta("1s"))
    else:
        deprecation = "true"
    if sunset_date:
        sunset = to_http_time(pd.Timestamp(sunset_date) - pd.Timedelta("1s"))
    else:
        sunset = None
    return deprecation, sunset
