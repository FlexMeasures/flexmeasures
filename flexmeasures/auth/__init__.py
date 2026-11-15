"""
Authentication and authorization policies and helpers.
"""

from flask import Flask, request
from flask_security import (
    Security,
    SQLAlchemySessionUserDatastore,
    password_reset,
    password_changed,
    reset_password_instructions_sent,
)
from flask_login import user_logged_in, current_user
from werkzeug.exceptions import BadRequest, Forbidden, Unauthorized

from flexmeasures.data import db


def register_at(app: Flask):

    from flexmeasures.auth.error_handling import (
        unauthenticated_handler,
        unauthenticated_handler_e,
    )  # noqa: F401
    from flexmeasures.auth.error_handling import (
        unauthorized_handler,
        unauthorized_handler_e,
    )  # noqa: F401
    from flexmeasures.data.models.user import (
        User,
        Role,
        remember_login,
        remember_last_seen,
        log_password_reset,
        log_password_changed,
        log_reset_password_instructions_sent,
    )  # noqa: F401

    # Setup Flask-Security-Too for user authentication & authorization
    user_datastore = SQLAlchemySessionUserDatastore(db.session, User, Role)
    app.security = Security(app, user_datastore)

    # Register custom auth problem handlers.
    # Note how we are switching authorization and authentication - read more about this in error_handling.py!
    # Flask-Security-Too seems to handle it the intended way:
    # https://flask-security-too.readthedocs.io/en/stable/api.html#flask_security.Security.unauthn_handler
    # is defaulting to 401.
    app.security.unauthn_handler(unauthenticated_handler)
    app.register_error_handler(Unauthorized, unauthenticated_handler_e)
    app.security.unauthz_handler(unauthorized_handler)
    app.register_error_handler(Forbidden, unauthorized_handler_e)

    # add our custom handler for a user login event
    user_logged_in.connect(remember_login)

    password_reset.connect(log_password_reset)
    password_changed.connect(log_password_changed)
    reset_password_instructions_sent.connect(log_reset_password_instructions_sent)

    # Flask-Security also accepts an auth token in the URL query (?auth_token=...),
    # from where it ends up in server and proxy logs, browser history and Referer headers.
    # Refuse such requests, before anything loads the user from that token.
    @app.before_request
    def refuse_auth_token_in_url():
        token_key = app.config.get("SECURITY_TOKEN_AUTHENTICATION_KEY", "auth_token")
        if token_key in request.args:
            raise BadRequest(
                f"Do not send auth tokens in the URL (as '{token_key}'). Use the {app.config.get('SECURITY_TOKEN_AUTHENTICATION_HEADER', 'Authorization')} header."
            )

    # also store when the last contact was
    @app.before_request
    def record_last_seen():
        remember_last_seen(current_user)
