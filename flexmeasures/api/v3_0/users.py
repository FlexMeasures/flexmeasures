from __future__ import annotations
from flask_classful import FlaskView, route
from marshmallow import fields
import marshmallow.validate as validate
from sqlalchemy.exc import IntegrityError
from sqlalchemy import and_, select, func, or_
from flask_sqlalchemy.pagination import SelectPagination
from webargs.flaskparser import use_kwargs
from flask_security import current_user, auth_required
from flask_security.recoverable import send_reset_password_instructions
from flask_json import as_json
from werkzeug.exceptions import Forbidden
from flexmeasures.auth.policy import check_access

from flexmeasures.data.models.audit_log import AuditLog
from flexmeasures.data.models.user import User as UserModel, Account
from flexmeasures.api.common.schemas.users import AccountIdField, UserIdField
from flexmeasures.api.common.schemas.search import SearchFilterField
from flexmeasures.api.v3_0.assets import get_accessible_accounts
from flexmeasures.data.queries.users import query_users_by_search_terms
from flexmeasures.data.schemas.account import AccountSchema
from flexmeasures.data.schemas.users import UserSchema
from flexmeasures.data.services.users import (
    set_random_password,
    remove_cookie_and_token_access,
)
from flexmeasures.auth.decorators import permission_required_for_context
from flexmeasures.data import db
from flexmeasures.utils.time_utils import server_now, naturalized_datetime_str

"""
API endpoints to manage users.

Both POST (to create) and DELETE are not accessible via the API, but as CLI functions.
"""

# Instantiate schemas outside of endpoint logic to minimize response time
user_schema = UserSchema()
users_schema = UserSchema(many=True)
partial_user_schema = UserSchema(partial=True)
account_schema = AccountSchema()


class UserAPI(FlaskView):
    route_base = "/users"
    trailing_slash = False
    decorators = [auth_required()]

    @route("", methods=["GET"])
    @use_kwargs(
        {
            "account": AccountIdField(data_key="account_id", load_default=None),
            "include_inactive": fields.Bool(load_default=False),
            "page": fields.Int(required=False, validate=validate.Range(min=1)),
            "per_page": fields.Int(
                required=False, validate=validate.Range(min=1), load_default=1
            ),
            "filter": SearchFilterField(required=False),
            "sort_by": fields.Str(
                required=False,
                validate=validate.OneOf(["username", "email", "lastLogin", "lastSeen"]),
            ),
            "sort_dir": fields.Str(
                required=False,
                validate=validate.OneOf(["asc", "desc"]),
            ),
        },
        location="query",
    )
    @as_json
    def index(
        self,
        account: Account,
        include_inactive: bool = False,
        page: int | None = None,
        per_page: int | None = None,
        filter: list[str] | None = None,
        sort_by: str | None = None,
        sort_dir: str | None = None,
    ):
        """
        API endpoint to list all users.

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
            accounts = get_accessible_accounts()

        filter_statement = UserModel.account_id.in_([a.id for a in accounts])

        if include_inactive is False:
            filter_statement = and_(filter_statement, UserModel.active.is_(True))

        query = query_users_by_search_terms(
            search_terms=filter, filter_statement=filter_statement
        )

        if sort_by is not None and sort_dir is not None:
            valid_sort_columns = {
                "username": UserModel.username,
                "email": UserModel.email,
                "lastLogin": UserModel.last_login_at,
                "lastSeen": UserModel.last_seen_at,
            }

            query = query.order_by(
                valid_sort_columns[sort_by].asc()
                if sort_dir == "asc"
                else valid_sort_columns[sort_by].desc()
            )

        if page is not None:
            num_records = db.session.scalar(
                select(func.count(UserModel.id)).where(filter_statement)
            )
            paginated_users: SelectPagination = db.paginate(
                query, per_page=per_page, page=page
            )

            users_response: list = [
                {
                    **user_schema.dump(user),
                    "account": account_schema.dump(user.account),
                    "flexmeasures_roles": [
                        role.name for role in user.flexmeasures_roles
                    ],
                    "last_login_at": naturalized_datetime_str(user.last_login_at),
                    "last_seen_at": naturalized_datetime_str(user.last_seen_at),
                }
                for user in paginated_users.items
            ]
            response: dict | list = {
                "data": users_response,
                "num-records": num_records,
                "filtered-records": paginated_users.total,
            }
        else:
            users = db.session.execute(query).scalars().all()
            response = [
                {
                    **user_schema.dump(user),
                    "account": account_schema.dump(user.account),
                    "flexmeasures_roles": [
                        role.name for role in user.flexmeasures_roles
                    ],
                    "last_login_at": naturalized_datetime_str(user.last_login_at),
                    "last_seen_at": naturalized_datetime_str(user.last_seen_at),
                }
                for user in users
            ]

        return response, 200

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
    def patch(self, id: int, user: UserModel, **user_data):  # noqa C901
        """API endpoint to patch user data.

        .. :quickref: User; Patch data for an existing user

        This endpoint sets data for an existing user.
        It has to be used by the user themselves, admins, consultant or account-admins (of the same account).
        Any subset of user fields can be sent.
        If the user is not an (account-)admin, they can only edit a few of their own fields.
        User roles cannot be updated by everyone - it requires certain access levels (roles, account), with the general rule that you need a higher access level than the role being updated.

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
        audit_event = ""  # we audit-log relevant changes
        for k, v in [(k, v) for k, v in user_data.items() if k in allowed_fields]:
            if current_user.id == user.id and k in ("active", "flexmeasures_roles"):
                raise Forbidden(
                    "Users who edit themselves cannot edit security-sensitive fields."
                )
            # if flexmeasures_roles is not empty, check if the user can modify the role
            if k == "flexmeasures_roles" and (v or len(v) == 0):
                from flexmeasures.auth.policy import can_modify_role

                current_roles = set(user.flexmeasures_roles)
                new_roles = set(v)

                roles_being_removed = current_roles - new_roles
                for role in roles_being_removed:
                    if not can_modify_role(current_user, [role], user):
                        raise Forbidden(
                            f"You are not allowed to remove ({role.name}) role from this user."
                        )
                if roles_being_removed:
                    audit_event += f"Removed role(s): [{','.join([r.name for r in roles_being_removed])}]."

                roles_being_added = new_roles - current_roles
                for role in roles_being_added:
                    if not can_modify_role(current_user, [role], user):
                        raise Forbidden(
                            f"You are not allowed to add ({role.name}) role to this user."
                        )
                if roles_being_added:
                    audit_event += f"Added role(s): [{','.join([r.name for r in roles_being_added])}]."

            setattr(user, k, v)
            if k == "active" and v is False:
                remove_cookie_and_token_access(user)
            if k == "active":
                audit_event += f"Active status set to '{v}'."
        if audit_event:
            user_audit_log = create_user_audit_log(audit_event, user)
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
    @use_kwargs(
        {
            "page": fields.Int(required=False, validate=validate.Range(min=1)),
            "per_page": fields.Int(
                required=False, validate=validate.Range(min=1), load_default=10
            ),
            "filter": SearchFilterField(required=False),
            "sort_by": fields.Str(
                required=False,
                validate=validate.OneOf(["event_datetime"]),
            ),
            "sort_dir": fields.Str(
                required=False,
                validate=validate.OneOf(["asc", "desc"]),
            ),
        },
        location="query",
    )
    @as_json
    def auditlog(
        self,
        id: int,
        user: UserModel,
        page: int | None = None,
        per_page: int | None = None,
        filter: list[str] | None = None,
        sort_by: str | None = None,
        sort_dir: str | None = None,
    ):
        """API endpoint to get history of user actions.

        .. :quickref: User; Get audit log

        The endpoint is paginated and supports search filters.
            - If the `page` parameter is not provided, all audit logs are returned paginated by `per_page` (default is 10).
            - If a `page` parameter is provided, the response will be paginated, showing a specific number of audit logs per page as defined by `per_page` (default is 10).
            - If `sort_by` (field name) and `sort_dir` ("asc" or "desc") are provided, the list will be sorted.
            - If a search 'filter' is provided, the response will filter out audit logs where each search term is either present in the event or active user name.
              The response schema for pagination is inspired by https://datatables.net/manual/server-side

        **Example response**

        .. sourcecode:: json
            {
                "data" : [
                    {
                        'event': 'User test user deleted',
                        'event_datetime': '2021-01-01T00:00:00',
                        'active_user_name': 'Test user',
                    }
                ],
                "num-records" : 1,
                "filtered-records" : 1
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
        query_statement = AuditLog.affected_user_id == user.id
        query = select(AuditLog).filter(query_statement)

        if filter:
            search_terms = filter[0].split(" ")
            query = query.filter(
                or_(
                    *[AuditLog.event.ilike(f"%{term}%") for term in search_terms],
                    *[
                        AuditLog.active_user_name.ilike(f"%{term}%")
                        for term in search_terms
                    ],
                )
            )

        if sort_by is not None and sort_dir is not None:
            valid_sort_columns = {"event_datetime": AuditLog.event_datetime}

            query = query.order_by(
                valid_sort_columns[sort_by].asc()
                if sort_dir == "asc"
                else valid_sort_columns[sort_by].desc()
            )

        if page is None:
            audit_logs = db.session.execute(query).scalars().all()

            response = [
                {
                    "event": audit_log.event,
                    "event_datetime": naturalized_datetime_str(
                        audit_log.event_datetime
                    ),
                    "active_user_name": audit_log.active_user_name,
                    "active_user_id": audit_log.active_user_id,
                }
                for audit_log in audit_logs
            ]
        else:
            select_pagination: SelectPagination = db.paginate(
                query, per_page=per_page, page=page
            )

            num_records = db.session.scalar(
                select(func.count(AuditLog.id)).where(query_statement)
            )

            audit_logs_response = [
                {
                    "event": audit_log.event,
                    "event_datetime": naturalized_datetime_str(
                        audit_log.event_datetime
                    ),
                    "active_user_name": audit_log.active_user_name,
                    "active_user_id": audit_log.active_user_id,
                }
                for audit_log in select_pagination.items
            ]

            response = {
                "data": audit_logs_response,
                "num-records": num_records,
                "filtered-records": select_pagination.total,
            }

        return response, 200


def create_user_audit_log(audit_event: str, user: UserModel):
    """
    Create audit log entry for changes on the user
    """
    active_user_id, active_user_name = None, None
    if hasattr(current_user, "id"):
        active_user_id, active_user_name = (
            current_user.id,
            current_user.username,
        )
    return AuditLog(
        event_datetime=server_now(),
        event=audit_event,
        active_user_id=active_user_id,
        active_user_name=active_user_name,
        affected_user_id=user.id,
        affected_account_id=user.account_id,
    )
