"""Refresh-token endpoints. These accept JSON credentials, never browser cookies."""

from flask_json import as_json
from marshmallow import Schema, fields, validate
from webargs.flaskparser import use_args

from flexmeasures.api import flexmeasures_api
from flexmeasures.auth.tokens import exchange_refresh_token


class RefreshTokenRequestSchema(Schema):
    refresh_token = fields.Str(
        data_key="refresh-token",
        attribute="refresh-token",
        required=True,
        validate=validate.Length(min=1),
        metadata={
            "description": "The current refresh token.",
            "example": "<refresh token>",
        },
    )


@flexmeasures_api.route("/refreshAuthToken", methods=["POST"])
@use_args(RefreshTokenRequestSchema, location="json")
@as_json
def refresh_auth_token(args):
    """
    .. :quickref: Auth; Exchange a refresh token
    ---
    post:
      summary: Rotate a refresh token and obtain a new access token.
      description: |
        No access token or password is required. Save the returned refresh token
        atomically and serialize refresh requests. Reuse revokes the token family.
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [refresh-token]
              properties:
                refresh-token:
                  type: string
      responses:
        200:
          description: New access and refresh token pair.
          content:
            application/json:
              schema:
                type: object
                properties:
                  auth_token:
                    type: string
                  user_id:
                    type: integer
                  refresh-token:
                    type: string
                  expires-in:
                    type: integer
                    nullable: true
                    description: Access-token lifetime in seconds, or null if unlimited.
        400:
          description: The JSON in the request body cannot be parsed.
        401:
          description: Invalid, expired or revoked refresh token. Authenticate again.
        422:
          description: UNPROCESSABLE_ENTITY
      tags:
        - Auth
    """
    return exchange_refresh_token(args["refresh-token"])


@flexmeasures_api.route("/revokeRefreshToken", methods=["POST"])
@use_args(RefreshTokenRequestSchema, location="json")
@as_json
def revoke_refresh_token(args):
    """
    .. :quickref: Auth; Revoke a refresh-token family
    ---
    post:
      summary: Revoke this refresh-token family.
      description: Existing access tokens remain valid until expiry or invalidation.
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [refresh-token]
              properties:
                refresh-token:
                  type: string
      responses:
        200:
          description: Refresh-token family revoked.
          content:
            application/json:
              schema:
                type: object
                properties:
                  revoked:
                    type: boolean
        400:
          description: The JSON in the request body cannot be parsed.
        401:
          description: Invalid, expired or revoked refresh token.
        422:
          description: UNPROCESSABLE_ENTITY
      tags:
        - Auth
    """
    return exchange_refresh_token(args["refresh-token"], revoke=True)
