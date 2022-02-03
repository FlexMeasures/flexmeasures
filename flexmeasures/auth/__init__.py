from flask import Flask
from flask_security import Security, SQLAlchemySessionUserDatastore
from flask_login import user_logged_in
from werkzeug.exceptions import Forbidden, Unauthorized

from flexmeasures.data import db


"""
Configure authentication and authorization.
"""


def register_at(app: Flask):

    from flexmeasures.auth.error_handling import (
        unauthenticated_handler,
        unauthenticated_handler_e,
    )  # noqa: F401
    from flexmeasures.auth.error_handling import (
        unauthorized_handler,
        unauthorized_handler_e,
    )  # noqa: F401
    from flexmeasures.data.models.user import User, Role, remember_login  # noqa: F401

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
