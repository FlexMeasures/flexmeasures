from flask_classful import FlaskView, route
from marshmallow import fields
from sqlalchemy.exc import IntegrityError
from webargs.flaskparser import use_kwargs
from flask_security import current_user
from flask_security.recoverable import send_reset_password_instructions
from flask_json import as_json
from werkzeug.exceptions import Forbidden

from flexmeasures.data.models.user import User as UserModel, Account
from flexmeasures.api.common.schemas.users import AccountIdField, UserIdField
from flexmeasures.data.schemas.users import UserSchema
from flexmeasures.data.services.users import (
    get_users,
    set_random_password,
    remove_cookie_and_token_access,
)
from flexmeasures.auth.decorators import permission_required_for_context
from flexmeasures.data import db

"""
API endpoints to manage users.

Both POST (to create) and DELETE are not accessible via the API, but as CLI functions.
"""

# Instantiate schemas outside of endpoint logic to minimize response time
user_schema = UserSchema()
users_schema = UserSchema(many=True)
partial_user_schema = UserSchema(partial=True)


class UserAPI(FlaskView):
    route_base = "/users"
    trailing_slash = False

    @route("", methods=["GET"])
    @use_kwargs(
        {
            "account": AccountIdField(
                data_key="account_id", load_default=AccountIdField.load_current
            ),
            "include_inactive": fields.Bool(load_default=False),
        },
        location="query",
    )
    @permission_required_for_context("read", ctx_arg_name="account")
    @as_json
    def index(self, account: Account, include_inactive: bool = False):
        """API endpoint to list all users of an account.

        .. :quickref: User; Download user list

        This endpoint returns all accessible users.
        By default, only active users are returned.
        The `include_inactive` query parameter can be used to also fetch
        inactive users.
        Accessible users are users in the same account as the current user.
        Only admins can use this endpoint to fetch users from a different account (by using the `account_id` query parameter).

        **Example response**

        An example of one user being returned:

        .. sourcecode:: json

            [
                {
                    'active': True,
                    'email': 'test_prosumer@seita.nl',
                    'account_id': 13,
                    'flexmeasures_roles': [1, 3],
                    'id': 1,
                    'timezone': 'Europe/Amsterdam',
                    'username': 'Test Prosumer User'
                }
            ]

        :reqheader Authorization: The authentication token
        :reqheader Content-Type: application/json
        :resheader Content-Type: application/json
        :status 200: PROCESSED
        :status 400: INVALID_REQUEST
        :status 401: UNAUTHORIZED
        :status 403: INVALID_SENDER
        :status 422: UNPROCESSABLE_ENTITY
        """
        users = get_users(account_name=account.name, only_active=not include_inactive)
        return users_schema.dump(users), 200

    @route("/<id>")
    @use_kwargs({"user": UserIdField(data_key="id")}, location="path")
    @permission_required_for_context("read", ctx_arg_name="user")
    @as_json
    def get(self, id: int, user: UserModel):
        """API endpoint to get a user.

        .. :quickref: User; Get a user

        This endpoint gets a user.
        Only admins or the members of the same account can use this endpoint.

        **Example response**

        .. sourcecode:: json

            {
                'account_id': 1,
                'active': True,
                'email': 'test_prosumer@seita.nl',
                'flexmeasures_roles': [1, 3],
                'id': 1,
                'timezone': 'Europe/Amsterdam',
                'username': 'Test Prosumer User'
            }

        :reqheader Authorization: The authentication token
        :reqheader Content-Type: application/json
        :resheader Content-Type: application/json
        :status 200: PROCESSED
        :status 400: INVALID_REQUEST, REQUIRED_INFO_MISSING, UNEXPECTED_PARAMS
        :status 401: UNAUTHORIZED
        :status 403: INVALID_SENDER
        :status 422: UNPROCESSABLE_ENTITY
        """
        return user_schema.dump(user), 200

    @route("/<id>", methods=["PATCH"])
    @use_kwargs(partial_user_schema)
    @use_kwargs({"user": UserIdField(data_key="id")}, location="path")
    @permission_required_for_context("update", ctx_arg_name="user")
    @as_json
    def patch(self, id: int, user: UserModel, **user_data):
        """API endpoint to patch user data.

        .. :quickref: User; Patch data for an existing user

        This endpoint sets data for an existing user.
        It has to be used by the user themselves, admins or account-admins (of the same account).
        Any subset of user fields can be sent.
        If the user is not an (account-)admin, they can only edit a few of their own fields.

        The following fields are not allowed to be updated at all:
         - id
         - account_id

        **Example request**

        .. sourcecode:: json

            {
                "active": false,
            }

        **Example response**

        The following user fields are returned:

        .. sourcecode:: json

            {
                'account_id': 1,
                'active': True,
                'email': 'test_prosumer@seita.nl',
                'flexmeasures_roles': [1, 3],
                'id': 1,
                'timezone': 'Europe/Amsterdam',
                'username': 'Test Prosumer User'
            }

        :reqheader Authorization: The authentication token
        :reqheader Content-Type: application/json
        :resheader Content-Type: application/json
        :status 200: UPDATED
        :status 400: INVALID_REQUEST, REQUIRED_INFO_MISSING, UNEXPECTED_PARAMS
        :status 401: UNAUTHORIZED
        :status 403: INVALID_SENDER
        :status 422: UNPROCESSABLE_ENTITY
        """
        allowed_fields = [
            "email",
            "username",
            "active",
            "timezone",
            "flexmeasures_roles",
        ]
        for k, v in [(k, v) for k, v in user_data.items() if k in allowed_fields]:
            if current_user.id == user.id and k in ("active", "flexmeasures_roles"):
                raise Forbidden(
                    "Users who edit themselves cannot edit security-sensitive fields."
                )
            setattr(user, k, v)
            if k == "active" and v is False:
                remove_cookie_and_token_access(user)
        db.session.add(user)
        try:
            db.session.commit()
        except IntegrityError as ie:
            return (
                dict(message="Duplicate user already exists", detail=ie._message()),
                400,
            )
        return user_schema.dump(user), 200

    @route("/<id>/password-reset", methods=["PATCH"])
    @use_kwargs({"user": UserIdField(data_key="id")}, location="path")
    @permission_required_for_context("update", ctx_arg_name="user")
    @as_json
    def reset_user_password(self, id: int, user: UserModel):
        """API endpoint to reset the user's current password, cookies and auth tokens, and to email a password reset link to the user.

        .. :quickref: User; Password reset

        Reset the user's password, and send them instructions on how to reset the password.
        This endpoint is useful from a security standpoint, in case of worries the password might be compromised.
        It sets the current password to something random, invalidates cookies and auth tokens,
        and also sends an email for resetting the password to the user.

        Users can reset their own passwords. Only admins can use this endpoint to reset passwords of other users.

        :reqheader Authorization: The authentication token
        :reqheader Content-Type: application/json
        :resheader Content-Type: application/json
        :status 200: PROCESSED
        :status 400: INVALID_REQUEST, REQUIRED_INFO_MISSING, UNEXPECTED_PARAMS
        :status 401: UNAUTHORIZED
        :status 403: INVALID_SENDER
        :status 422: UNPROCESSABLE_ENTITY
        """
        set_random_password(user)
        remove_cookie_and_token_access(user)
        send_reset_password_instructions(user)

        # commit only if sending instructions worked, as well
        db.session.commit()
