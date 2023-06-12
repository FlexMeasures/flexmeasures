from __future__ import annotations

from typing import Any

from flask import abort, current_app, request, Blueprint, Response, after_this_request
from flask_security.core import current_user
import pandas as pd

from flexmeasures.utils.time_utils import to_http_time


def sunset_blueprint(
    blueprint,
    api_version_being_sunset: str,
    sunset_link: str,
    api_version_upgrade_to: str = "3.0",
    rollback_possible: bool = True,
    **kwargs,
):
    """Sunsets every route on a blueprint by returning 410 (Gone) responses, if sunset is active.

    Whether the sunset is active can be toggled using the config setting "FLEXMEASURES_API_SUNSET_ACTIVE".
    If the sunset is inactive, this function will not affect any requests in this blueprint.
    If the endpoint implementations have been removed, set rollback_possible=False.

    Errors will be logged by utils.error_utils.error_handling_router.
    """

    def return_410_unless_host_rolls_back_sunrise():

        if (
            rollback_possible
            and not current_app.config["FLEXMEASURES_API_SUNSET_ACTIVE"]
        ):
            # Sunset is inactive and blueprint contents should still be there,
            # so we let the request pass to the endpoint implementation
            pass
        else:
            # Override with custom info link, if set by host
            link = override_from_config(sunset_link, "FLEXMEASURES_API_SUNSET_LINK")

            abort(
                410,
                f"API version {api_version_being_sunset} has been sunset. Please upgrade to API version {api_version_upgrade_to}. See {link} for more information.",
            )

    blueprint.before_request(return_410_unless_host_rolls_back_sunrise)


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
    deprecation = _format_deprecation(deprecation_date)
    sunset = _format_sunset(sunset_date)

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

            # Override sunset date if host used corresponding config setting
            _sunset = override_from_config(sunset, "FLEXMEASURES_API_SUNSET_DATE")

            # Override sunset link if host used corresponding config setting
            _sunset_link = override_from_config(
                sunset_link, "FLEXMEASURES_API_SUNSET_LINK"
            )

            return _add_headers(
                response,
                deprecation,
                deprecation_link,
                _sunset,
                _sunset_link,
            )
        return response


def deprecate_blueprint(
    blueprint: Blueprint,
    deprecation_date: pd.Timestamp | str | None = None,
    deprecation_link: str | None = None,
    sunset_date: pd.Timestamp | str | None = None,
    sunset_link: str | None = None,
    **kwargs,
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
    deprecation = _format_deprecation(deprecation_date)
    sunset = _format_sunset(sunset_date)

    def _after_request_handler(response: Response) -> Response:
        current_app.logger.warning(
            f"Deprecated endpoint {request.endpoint} called by {current_user}"
        )

        # Override sunset date if host used corresponding config setting
        _sunset = override_from_config(sunset, "FLEXMEASURES_API_SUNSET_DATE")

        # Override sunset link if host used corresponding config setting
        _sunset_link = override_from_config(sunset_link, "FLEXMEASURES_API_SUNSET_LINK")

        return _add_headers(
            response,
            deprecation,
            deprecation_link,
            _sunset,
            _sunset_link,
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


def _format_deprecation(deprecation_date):
    if deprecation_date:
        deprecation = to_http_time(pd.Timestamp(deprecation_date) - pd.Timedelta("1s"))
    else:
        deprecation = "true"
    return deprecation


def _format_sunset(sunset_date):
    if sunset_date:
        sunset = to_http_time(pd.Timestamp(sunset_date) - pd.Timedelta("1s"))
    else:
        sunset = None
    return sunset


def override_from_config(setting: Any, config_setting_name: str) -> Any:
    """Override setting by config setting, unless the latter is None or is missing."""
    config_setting = current_app.config.get(config_setting_name)
    if config_setting is not None:
        _setting = config_setting
    else:
        _setting = setting
    return _setting
