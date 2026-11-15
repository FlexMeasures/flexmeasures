"""
FlexMeasures API routes and implementations.
"""

from flask import Flask, Blueprint, request, current_app
import html
from flask_security.utils import verify_password
from flask_json import as_json
from flask_login import current_user
from webargs.flaskparser import use_args
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select

from flexmeasures.data import db
from flexmeasures import __version__ as flexmeasures_version
from flexmeasures.api.common import rate_limiting
from flexmeasures.api.common.utils.api_utils import catch_timed_belief_replacements
from flexmeasures.data.models.user import User
from flexmeasures.api.common.utils.args_parsing import (
    validation_error_handler,
    request_entity_too_large_handler,
)
from flexmeasures.api.common.responses import invalid_sender
from flexmeasures.data.schemas.utils import FMValidationError
from werkzeug.exceptions import RequestEntityTooLarge
from flexmeasures.api.v3_0.users import AuthRequestSchema
from flexmeasures.auth.event_logging import email_fingerprint, log_authentication_event

# The api blueprint. It is registered with the Flask app (see app.py)
flexmeasures_api = Blueprint("flexmeasures_api", __name__)


def _requires_second_factor(user: User) -> bool:
    """Whether logging in as this user requires a second factor (as it does in the UI)."""
    return bool(
        current_app.config.get("SECURITY_TWO_FACTOR")
        and user.tf_primary_method
        and user.tf_totp_secret
    )


@flexmeasures_api.route("/requestAuthToken", methods=["POST"])
@use_args(AuthRequestSchema, location="json")
@as_json
def request_auth_token(args) -> tuple[dict, int]:
    """
    .. :quickref: Auth; Obtain authentication token
    ---
    post:
      summary: Obtain a fresh authentication access token.
      description: |
          Retrieve a short-lived authentication token using email and password. The lifetime of this token depends on the current system setting
          SECURITY_TOKEN_MAX_AGE.

          On servers with two-factor authentication (SECURITY_TWO_FACTOR), users who log in with a second factor
          cannot get a token with their password alone: they log in first (completing the second factor),
          and then call this endpoint from that session. Hosts can allow password-only tokens again with
          FLEXMEASURES_ALLOW_PASSWORD_TOKENS_WITH_2FA.

      requestBody:
        required: true
        content:
          application/json:
            schema: AuthRequestSchema
      responses:
        200:
          description: Token successfully generated
          content:
            application/json:
              schema:
                type: object
                properties:
                  authentication_token:
                    type: string
                    description: |
                      Short-lived authentication token, which can be used in request headers using `{"Authorization": authentication_token}`.
        400:
          description: INVALID_REQUEST
        401:
          description: UNAUTHORIZED
      tags:
        - Auth
    """
    try:
        if not request.is_json:
            return {"errors": ["Content-type of request must be application/json"]}, 400
        if "email" not in request.json:
            return {"errors": ["Please provide the 'email' parameter."]}, 400

        email = request.json["email"]
        if current_user.is_authenticated and current_user.email == email:
            user = current_user
            issued_by = "session"
        else:
            issued_by = "password"
            user = db.session.execute(
                select(User).filter_by(email=email)
            ).scalar_one_or_none()
            if not user:
                log_authentication_event(
                    f"token requested for an unknown email address (hash {email_fingerprint(str(email))})",
                    failed=True,
                )
                return (
                    {
                        "errors": [
                            "User with email '%s' does not exist" % html.escape(email)
                        ]
                    },
                    404,
                )

            if "password" not in request.json:
                return {"errors": ["Please provide the 'password' parameter."]}, 400
            if not verify_password(request.json["password"], user.password):
                # Counts against the user's failed attempts (see flexmeasures.auth.login_throttling)
                # Logged through Flask-Security's user_failed_authn signal (see flexmeasures.auth.event_logging)
                user.track_failed_authn("password")
                return {"errors": ["User password does not match."]}, 401
            if _requires_second_factor(user) and not current_app.config.get(
                "FLEXMEASURES_ALLOW_PASSWORD_TOKENS_WITH_2FA", False
            ):
                return (
                    {
                        "errors": [
                            "This user logs in with two-factor authentication, so a password alone cannot get a token."
                            " Log in (with your second factor) and request a token from that session."
                        ]
                    },
                    401,
                )
        token = user.get_auth_token()
        log_authentication_event(
            f"auth token issued to user {user.id} (by {issued_by})"
        )
        return {"auth_token": token, "user_id": user.id}
    except Exception as e:
        current_app.logger.error(f"Exception in /requestAuthToken endpoint: {e}")
        return {"errors": ["An internal error has occurred."]}, 500


@flexmeasures_api.route("/", methods=["GET"])
@as_json
def get_versions() -> dict:
    """
    .. :quickref: Public; List available API versions
    ---
    get:
      summary: List available API versions
      description: |
        Public endpoint to list all available FlexMeasures API versions.

        This can be used to programmatically discover which API versions
        are currently supported and their base URLs.
      responses:
        200:
          description: Successfully retrieved available API versions.
          content:
            application/json:
              schema:
                type: object
                properties:
                  message:
                    type: string
                    example: "For these API versions a public endpoint is available, listing its service."
                  versions:
                    type: array
                    items:
                      type: string
                    example: ["v3_0"]
                  flexmeasures_version:
                    type: string
                    example: "0.18.3"
      tags:
        - Public
    """

    response = {
        "message": (
            "For these API versions a public endpoint is available, listing its service. For example: "
            "/api/v3_0. An authentication token can be requested at: "
            "/api/requestAuthToken"
        ),
        "versions": ["v3_0"],
        "flexmeasures_version": flexmeasures_version,
    }
    return response


def register_at(app: Flask):
    """This can be used to register this blueprint together with other api-related things"""

    # handle API specific errors
    app.register_error_handler(FMValidationError, validation_error_handler)
    app.register_error_handler(RequestEntityTooLarge, request_entity_too_large_handler)
    app.register_error_handler(IntegrityError, catch_timed_belief_replacements)
    app.unauthorized_handler_api = invalid_sender

    rate_limiting.register_at(app)

    app.register_blueprint(
        flexmeasures_api, url_prefix="/api"
    )  # now registering the blueprint will affect all endpoints

    # Add version headers to all API responses
    @app.after_request
    def add_version_headers(response):
        if request.path.startswith("/api/"):
            response.headers["FlexMeasures-Version"] = flexmeasures_version
            if request.path.startswith("/api/v3_0"):
                response.headers["API-Version"] = "v3_0"
        return response

    # Load API endpoints for internal operations
    from flexmeasures.api.common import register_at as ops_register_at

    ops_register_at(app)

    # Load all versions of the API functionality
    from flexmeasures.api.v3_0 import register_at as v3_0_register_at
    from flexmeasures.api.dev import register_at as dev_register_at
    from flexmeasures.api.sunset import register_at as sunset_register_at

    v3_0_register_at(app)
    dev_register_at(app)
    sunset_register_at(app)
