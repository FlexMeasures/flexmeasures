from flask import Flask, request, jsonify, current_app
from flask_sqlalchemy import SQLAlchemy
from flask_security import Security, SQLAlchemySessionUserDatastore
from flask_login import user_logged_in

from bvp.data.models.user import User, Role, remember_login


UNAUTH_ERROR_CLASS = "Forbidden"
UNAUTH_MSG = "You cannot be authorized for this content for function."
# We only can have one with flask security, so we opt for 403: Forbidden.
UNAUTH_STATUS_CODE = 403


def configure_auth(app: Flask, db: SQLAlchemy):

    # Setup Flask-Security for user authentication & authorization
    user_datastore = SQLAlchemySessionUserDatastore(db.session, User, Role)
    app.security = Security(app, user_datastore)
    user_logged_in.connect(remember_login)

    # Register custom auth problem handlers
    app.security.unauthorized_handler(unauth_handler)


def unauth_handler():
    """
    Generic handler for auth problems.
    We support json if the request supports it.
    The ui package can also define how it wants to render HTML errors.
    """
    if request.is_json:
        return (
            jsonify(dict(message="%s:%s" % (UNAUTH_ERROR_CLASS, UNAUTH_MSG))),
            UNAUTH_STATUS_CODE,
        )
    elif hasattr(current_app, "unauth_handler_html"):
        return current_app.unauth_handler_html()
    else:
        return "%s:%s" % (UNAUTH_ERROR_CLASS, UNAUTH_MSG), UNAUTH_STATUS_CODE
