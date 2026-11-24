"""
FlexMeasures API routes and implementations.
"""

from flask import Flask, Blueprint, request, current_app
from flask_security.utils import hash_password, verify_password
from flask_json import as_json
from flask_login import current_user
from webargs.flaskparser import use_args
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy import select

from flexmeasures.data import db
from flexmeasures import __version__ as flexmeasures_version
from flexmeasures.api.common import rate_limiting
from flexmeasures.api.common.utils.api_utils import (
    catch_timed_belief_replacements,
    handle_belief_replacement_not_allowed,
)
from flexmeasures.data.services.data_ingestion import BeliefReplacementNotAllowed
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

          The password is required also when the request comes from a logged-in session. Deactivated users get no token.

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
                  auth_token:
                    type: string
                    description: |
                      Short-lived access token, used as `{"Authorization": auth_token}`.
                  user_id:
                    type: integer
                  refresh-token:
                    type: string
                    description: Returned only when include-refresh-token is true.
                  expires-in:
                    type: integer
                    description: Access-token lifetime in seconds, returned with refresh-token.
        400:
          description: INVALID_REQUEST
        401:
          description: UNAUTHORIZED
        409:
          description: The user's active API refresh-token family limit has been reached.
          content:
            application/json:
              schema:
                type: object
                properties:
                  error:
                    type: string
                    example: refresh_token_family_limit
                  errors:
                    type: array
                    items:
                      type: string
        422:
          description: Invalid request fields, such as an invalid include-refresh-token value.
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
            # A session alone does not get a token: that would turn a copied session cookie into a portable credential
            if "password" not in request.json:
                return {"errors": ["Please provide the 'password' parameter."]}, 400
            if not verify_password(request.json["password"], user.password):
                user.track_failed_authn("password")
                return {"errors": ["User password does not match."]}, 401
        else:
            issued_by = "password"
            if "password" not in request.json:
                return {"errors": ["Please provide the 'password' parameter."]}, 400
            user = db.session.execute(
                select(User).filter_by(email=email)
            ).scalar_one_or_none()
            if not user:
                log_authentication_event(
                    f"token requested for an unknown email address (hash {email_fingerprint(str(email))})",
                    failed=True,
                )
                # Answer as for a wrong password, and take as long, so the answer does not tell which email addresses have an account
                hash_password(str(request.json["password"]))
                return {"errors": ["User password does not match."]}, 401
            if not verify_password(request.json["password"], user.password):
                # Counts against the user's failed attempts, and is logged, through Flask-Security's user_failed_authn signal
                # (see flexmeasures.auth.login_throttling and flexmeasures.auth.event_logging)
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
            if "password" not in request.json:
                return {"errors": ["Please provide the 'password' parameter."]}, 400
            if not verify_password(request.json["password"], user.password):
                return {"errors": ["User password does not match."]}, 401
        if not user.active:
            # Flask-Security would refuse the token anyway; do not issue it
            return {"errors": ["This user is deactivated."]}, 401
        if args["include-refresh-token"]:
            # Serialize issuance with deactivation/password changes, then verify
            # credentials again against the locked, up-to-date user record.
            from flexmeasures.auth.tokens import issue_refresh_token

            user = db.session.scalar(
                select(User)
                .where(User.id == user.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if not user or not verify_password(args["password"], user.password):
                return {"errors": ["User password does not match."]}, 401
            return issue_refresh_token(user)

        token = user.get_auth_token()
        log_authentication_event(
            f"auth token issued to user {user.id} (by {issued_by})"
        )
        return {"auth_token": token, "user_id": user.id}
    except SQLAlchemyError as e:
        db.session.rollback()
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
    app.register_error_handler(
        BeliefReplacementNotAllowed, handle_belief_replacement_not_allowed
    )
    app.unauthorized_handler_api = invalid_sender

    rate_limiting.register_at(app)

    from flexmeasures.api import refresh_tokens  # noqa: F401

    app.register_blueprint(
        flexmeasures_api, url_prefix="/api"
    )  # now registering the blueprint will affect all endpoints

    # Add version headers to all API responses
    @app.after_request
    def add_version_headers(response):
        if request.endpoint in {
            "flexmeasures_api.request_auth_token",
            "flexmeasures_api.refresh_auth_token",
            "flexmeasures_api.revoke_refresh_token",
        }:
            response.headers["Cache-Control"] = "no-store"
            response.headers["Pragma"] = "no-cache"
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
    from flexmeasures.api.ui import register_at as ui_register_at
    from flexmeasures.api.sunset import register_at as sunset_register_at

    v3_0_register_at(app)
    ui_register_at(app)
    sunset_register_at(app)
