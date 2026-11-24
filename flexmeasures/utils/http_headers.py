"""
HTTP response headers that harden every response FlexMeasures sends
"""

from __future__ import annotations

from flask import Flask, Response, current_app


def set_security_headers(response: Response) -> Response:
    """Add the headers in FLEXMEASURES_SECURITY_HEADERS to a response.

    A header the view (or an extension) already set is kept as it is.
    A header whose configured value is empty or None is not sent, so hosts can switch off each one,
    for example when their reverse proxy adds it already.
    """
    for name, value in current_app.config.get(
        "FLEXMEASURES_SECURITY_HEADERS", {}
    ).items():
        if value and name not in response.headers:
            response.headers[name] = value
    return response


def register_security_headers(app: Flask):
    app.after_request(set_security_headers)
