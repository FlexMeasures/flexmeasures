from flask_classful import FlaskView, route
from marshmallow import fields
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select
from webargs.flaskparser import use_kwargs
from flask_security import current_user, auth_required
from flask_security.recoverable import send_reset_password_instructions
from flask_json import as_json
from werkzeug.exceptions import Forbidden, Unauthorized
from flexmeasures.auth.policy import check_access

from flexmeasures.data.models.audit_log import AuditLog
from flexmeasures.data.models.user import User as UserModel, Account
from flexmeasures.api.common.schemas.users import AccountIdField, UserIdField
from flexmeasures.data.schemas.users import UserSchema
from flexmeasures.data.services.users import (
    get_users,
    set_random_password,
    remove_cookie_and_token_access,
    get_audit_log_records,
)
from flexmeasures.auth.decorators import permission_required_for_context
from flexmeasures.data import db
from flexmeasures.utils.time_utils import server_now

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
    decorators = [auth_required()]

    @route("", methods=["GET"])
    @use_kwargs(
        {
            "account": AccountIdField(data_key="account_id", load_default=None),
            "include_inactive": fields.Bool(load_default=False),
        },
        location="query",
    )
    @as_json
    def index(self, account: Account, include_inactive: bool = False):
        """API endpoint to list all users.


        .. :quickref: User; Download user list

        This endpoint returns all accessible users.
        By default, only active users are returned.
        The `account_id` query parameter can be used to filter the users of
        a given account.
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

        if account is not None:
            check_access(account, "read")
            accounts = [account]
        else:
            accounts = []
            for account in db.session.scalars(select(Account)).all():
                try:
                    check_access(account, "read")
                    accounts.append(account)
                except (Forbidden, Unauthorized):
                    pass

        users = []
        for account in accounts:
            users += get_users(
                account_name=account.name,
                only_active=not include_inactive,
            )
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
            if k == "active":
                active_user_id, active_user_name = None, None
                if hasattr(current_user, "id"):
                    active_user_id, active_user_name = (
                        current_user.id,
                        current_user.username,
                    )
                user_audit_log = AuditLog(
                    event_datetime=server_now(),
                    event=f"Active status set to '{v}' for user {user.username}",
                    active_user_id=active_user_id,
                    active_user_name=active_user_name,
                    affected_user_id=user.id,
                    affected_account_id=user.account_id,
                )
                db.session.add(user_audit_log)
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

    @route("/<id>/auditlog")
    @use_kwargs({"user": UserIdField(data_key="id")}, location="path")
    @permission_required_for_context(
        "read",
        ctx_arg_name="user",
        pass_ctx_to_loader=True,
        ctx_loader=AuditLog.user_table_acl,
    )
    @as_json
    def auditlog(self, id: int, user: UserModel):
        """API endpoint to get history of user actions.
        **Example response**

        .. sourcecode:: json
            [
                {
                    'event': 'User test user deleted',
                    'event_datetime': '2021-01-01T00:00:00',
                    'active_user_name': 'Test user',
                }
            ]

        :reqheader Authorization: The authentication token
        :reqheader Content-Type: application/json
        :resheader Content-Type: application/json
        :status 200: PROCESSED
        :status 400: INVALID_REQUEST, REQUIRED_INFO_MISSING, UNEXPECTED_PARAMS
        :status 401: UNAUTHORIZED
        :status 403: INVALID_SENDER
        :status 422: UNPROCESSABLE_ENTITY
        """
        audit_logs = get_audit_log_records(user)
        audit_logs = [
            {
                k: getattr(log, k)
                for k in (
                    "event",
                    "event_datetime",
                    "active_user_name",
                    "active_user_id",
                )
            }
            for log in audit_logs
        ]
        return audit_logs, 200
