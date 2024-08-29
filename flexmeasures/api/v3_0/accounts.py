from __future__ import annotations

from flask_classful import FlaskView, route
from flexmeasures.data import db
from webargs.flaskparser import use_kwargs, use_args
from flask_security import current_user, auth_required
from flask_json import as_json

from flexmeasures.auth.policy import user_has_admin_access
from flexmeasures.auth.decorators import permission_required_for_context
from flexmeasures.data.models.audit_log import AuditLog
from flexmeasures.data.models.user import Account
from flexmeasures.data.services.accounts import get_accounts, get_audit_log_records
from flexmeasures.api.common.schemas.users import AccountIdField
from flexmeasures.data.schemas.account import AccountSchema
from flexmeasures.utils.time_utils import server_now

"""
API endpoints to manage accounts.

Both POST (to create) and DELETE are not accessible via the API, but as CLI functions.
Editing (PATCH) is also not yet implemented, but might be next, e.g. for the name or roles.
"""

# Instantiate schemas outside of endpoint logic to minimize response time
account_schema = AccountSchema()
accounts_schema = AccountSchema(many=True)
partial_account_schema = AccountSchema(partial=True)


class AccountAPI(FlaskView):
    route_base = "/accounts"
    trailing_slash = False
    decorators = [auth_required()]

    @route("", methods=["GET"])
    @as_json
    def index(self):
        """API endpoint to list all accounts accessible to the current user.

        .. :quickref: Account; Download account list

        This endpoint returns all accessible accounts.
        Accessible accounts are your own account and accounts you are a consultant for, or all accounts for admins.

        **Example response**

        An example of one account being returned:

        .. sourcecode:: json

            [
                {
                    'id': 1,
                    'name': 'Test Account'
                    'account_roles': [1, 3],
                    'consultancy_account_id': 2,
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
        if user_has_admin_access(current_user, "read"):
            accounts = get_accounts()
        else:
            accounts = [current_user.account] + (
                current_user.account.consultancy_client_accounts
                if "consultant" in current_user.roles
                else []
            )

        return accounts_schema.dump(accounts), 200

    @route("/<id>", methods=["GET"])
    @use_kwargs({"account": AccountIdField(data_key="id")}, location="path")
    @permission_required_for_context("read", ctx_arg_name="account")
    @as_json
    def get(self, id: int, account: Account):
        """API endpoint to get an account.

        .. :quickref: Account; Get an account

        This endpoint retrieves an account, given its id.
        Only admins, consultants and users belonging to the account itself can use this endpoint.

        **Example response**

        .. sourcecode:: json

            {
                'id': 1,
                'name': 'Test Account'
                'account_roles': [1, 3],
                'consultancy_account_id': 2,
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

        return account_schema.dump(account), 200

    @route("/<id>", methods=["PATCH"])
    @use_args(partial_account_schema)
    @use_kwargs({"account": AccountIdField(data_key="id")}, location="path")
    @permission_required_for_context("update", ctx_arg_name="account")
    @as_json
    def patch(self, account_data: dict, id: int, account: Account):
        """Update an account given its identifier.

        .. :quickref: Account; Update an account

        This endpoint sets data for an existing account.

        The following fields are not allowed to be updated:
        - id

        The following fields are only editable if user role is admin:
        - consultancy_account_id

        **Example request**

        .. sourcecode:: json

            {
                'name': 'Test Account'
                'primary_color': '#1a3443'
                'secondary_color': '#f1a122'
                'logo_url': 'https://example.com/logo.png'
                'consultancy_account_id': 2,
            }


        **Example response**

        The whole account is returned in the response:

        .. sourcecode:: json

            {
                'id': 1,
                'name': 'Test Account'
                'account_roles': [1, 3],
                'primary_color': '#1a3443'
                'secondary_color': '#f1a122'
                'logo_url': 'https://example.com/logo.png'
                'consultancy_account_id': 2,
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

        # Get existing consultancy_account_id
        existing_consultancy_account_id = (
            account.consultancy_account.id if account.consultancy_account else None
        )

        if not user_has_admin_access(current_user, "update"):
            # Remove consultancy_account_id from account_data if no admin access
            account_data.pop("consultancy_account_id", None)
        else:
            # Check if consultancy_account_id has changed
            new_consultancy_account_id = account_data.get("consultancy_account_id")
            if existing_consultancy_account_id != new_consultancy_account_id:
                new_consultant_account = db.session.query(Account).get(
                    new_consultancy_account_id
                )
                # Validate new consultant account
                if (
                    not new_consultant_account
                    or new_consultant_account.id == account.id
                ):
                    return {"errors": ["Invalid consultancy_account_id"]}, 422

        # Track modified fields
        fields_to_check = [
            "name",
            "primary_color",
            "secondary_color",
            "logo_url",
            "consultancy_account_id",
        ]

        # Compile modified fields string
        modified_fields_str = ", ".join(
            field
            for field in fields_to_check
            if account_data.get(field) != getattr(account, field)
        )

        for k, v in account_data.items():
            setattr(account, k, v)

        event_message = f"Account {account.name} has been updated. Modified fields: {modified_fields_str}"

        # Add Audit log
        account_audit_log = AuditLog(
            event_datetime=server_now(),
            event=event_message,
            active_user_id=current_user.id,
            active_user_name=current_user.username,
            affected_user_id=current_user.id,
            affected_account_id=account.id,
        )
        db.session.add(account_audit_log)
        db.session.commit()
        return account_schema.dump(account), 200

    @route("/<id>/auditlog", methods=["GET"])
    @use_kwargs({"account": AccountIdField(data_key="id")}, location="path")
    @permission_required_for_context(
        "read",
        ctx_arg_name="account",
        pass_ctx_to_loader=True,
        ctx_loader=AuditLog.account_table_acl,
    )
    @as_json
    def auditlog(self, id: int, account: Account):
        """API endpoint to get history of account actions.
        **Example response**

        .. sourcecode:: json
            [
                {
                    'event': 'User test user deleted',
                    'event_datetime': '2021-01-01T00:00:00',
                    'active_user_id': 1,
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
        audit_logs = get_audit_log_records(account)
        audit_logs = [
            {k: getattr(log, k) for k in ("event", "event_datetime", "active_user_id")}
            for log in audit_logs
        ]
        return audit_logs, 200
