"""
Utils for handling of errors
"""

import re
import sys
import traceback
from flask import Flask, jsonify, current_app, request
from werkzeug.exceptions import (
    HTTPException,
    InternalServerError,
    SecurityError,
)
from sqlalchemy.orm import Query


def log_error(exc: Exception, error_msg: str, verbose: bool = True):
    """Collect metadata about the exception and log it.
    error_msg comes in as an extra attribute because Exception implementations differ here.
    """
    exc_info = sys.exc_info()
    last_traceback = exc_info[2]

    if hasattr(exc, "__cause__") and exc.__cause__ is not None:
        exc_info = (exc.__cause__.__class__, exc.__cause__, last_traceback)

    extra = dict(url=request.path, **get_err_source_info(last_traceback))

    msg = '{error_name} - URL was: {url} - "{message}"'
    if verbose:
        msg += " [occurred at {src_module} (in {src_func}, line {src_linenr})"

    # Fill in message contents
    msg = msg.format(error_name=exc.__class__.__name__, message=error_msg, **extra)

    # Log error with or without traceback
    if verbose:
        current_app.logger.error(msg, exc_info=exc_info)
    else:
        current_app.logger.error(msg)


def get_err_source_info(original_traceback=None) -> dict:
    """Use this when an error is handled to get info on where it occurred."""
    try:  # carefully try to get the actual place where the error happened
        if not original_traceback:
            original_traceback = sys.exc_info()[2]  # class, exc, traceback
        first_call = traceback.extract_tb(original_traceback)[-1]
        return dict(
            src_module=first_call[0],
            src_linenr=first_call[1],
            src_func=first_call[2],
            src_code=first_call[3],
        )
    except Exception as e:
        current_app.warning(
            "I was unable to retrieve error source information: %s." % str(e)
        )
        return dict(module="", linenr=0, method="", src_code="")


def error_handling_router(error: Exception):
    """
    Generic handler for errors.
    We respond in JSON if the request content-type is JSON, if the request matched an API route (under /api),
    or if the error is a SecurityError.
    A URL under /api that matches no route (a 404) therefore gets the HTML error page, unless the request is JSON.
    Otherwise, the ui package can define how it wants to render HTML errors, by setting a function.

    Any exception that is not an HTTPException (e.g. a database error) is logged in full,
    and then answered as an InternalServerError.
    Its code attribute is not an HTTP status (SQLAlchemy errors carry codes like "f405"),
    which would otherwise end up in the response's status line,
    and its message may reveal internals (e.g. SQL), which belong in the logs only.
    """
    if not isinstance(error, HTTPException):
        log_error(error, str(error))
        error = InternalServerError(original_exception=error)
        http_error_code = 500
    else:
        http_error_code = error.code or 500  # a bare HTTPException has no code
        log_http_error(error, http_error_code)

    error_text = getattr(
        error, "description", f"Something went wrong: {error.__class__.__name__}"
    )
    if (
        request.is_json
        or (request.url_rule is not None and request.url_rule.rule.startswith("/api"))
        or isinstance(error, SecurityError)
    ):
        response = jsonify(
            dict(
                message=getattr(error, "description", str(error)),
                status=http_error_code,
            )
        )
        response.status_code = http_error_code
        return response
    # Can UI handle this specific type?
    elif hasattr(current_app, "%s_handler_html" % error.__class__.__name__):
        return getattr(current_app, "%s_handler_html" % error.__class__.__name__)(error)
    # Can UI handle HTTPException? Let's make one from the error.
    elif hasattr(current_app, "HttpException_handler_html"):
        return current_app.HttpException_handler_html(error)
    # This fallback is ugly but better than nothing.
    else:
        return "%s: %s" % (error.__class__.__name__, error_text), http_error_code


def log_http_error(error: HTTPException, http_error_code: int):
    """Log an HTTPException, leaving out the traceback where it is not interesting."""
    if http_error_code == 404:
        # For 404 Not Found we only log the name, because the description is just 'The requested URL was not found on the server. If you entered the URL manually please check your spelling and try again.'
        log_error(
            error,
            error.name,
            verbose=False,  # not interesting
        )
    elif http_error_code in (401, 403, 410) or isinstance(error, SecurityError):
        log_error(
            error,
            error.description,
            verbose=False,
        )
    else:
        log_error(error, getattr(error, "description", str(error)))


def add_basic_error_handlers(app: Flask):
    """
    Register a generic error handler for all exceptions.
    See also the auth package for auth-specific error handling (Unauthorized, Forbidden)
    """
    app.register_error_handler(Exception, error_handling_router)


def print_query(query: Query) -> str:
    """Print full SQLAlchemy query with compiled parameters.

    Recommended use as developer tool only.

    Adapted from https://stackoverflow.com/a/63900851/13775459
    """
    regex = re.compile(r":(?P<name>\w+)")
    params = query.statement.compile().params
    sql = regex.sub(r"'{\g<name>}'", str(query.statement)).format(**params)
    from flexmeasures.data import db

    print(f"\nPrinting SQLAlchemy query to database {db.engine.url.database}:\n\n")
    print(sql)
    return sql
