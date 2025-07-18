from __future__ import annotations

from flask_classful import FlaskView, route
from flexmeasures.data import db
from webargs.flaskparser import use_kwargs, use_args
from flask_security import current_user, auth_required
from flask_json import as_json
from sqlalchemy import or_, select, func

from marshmallow import fields
import marshmallow.validate as validate
from flask_sqlalchemy.pagination import SelectPagination


from flexmeasures.auth.policy import user_has_admin_access
from flexmeasures.auth.decorators import permission_required_for_context
from flexmeasures.data.models.audit_log import AuditLog
from flexmeasures.data.models.user import Account, User
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.services.accounts import get_accounts, get_audit_log_records
from flexmeasures.api.common.schemas.users import AccountIdField
from flexmeasures.data.schemas.account import AccountSchema
from flexmeasures.api.common.schemas.search import SearchFilterField
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
    @use_kwargs(
        {
            "page": fields.Int(required=False, validate=validate.Range(min=1)),
            "per_page": fields.Int(
                required=False, validate=validate.Range(min=1), load_default=10
            ),
            "filter": SearchFilterField(required=False),
            "sort_by": fields.Str(
                required=False,
                validate=validate.OneOf(["id", "name", "assets", "users"]),
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
        page: int | None = None,
        per_page: int | None = None,
        filter: list[str] | None = None,
        sort_by: str | None = None,
        sort_dir: str | None = None,
    ):
        """API endpoint to list all accounts accessible to the current user.

        .. :quickref: Account; Download account list

        This endpoint returns all accessible accounts.
        Accessible accounts are your own account and accounts you are a consultant for, or all accounts for admins.

        The endpoint supports pagination of the asset list using the `page` and `per_page` query parameters.

            - If the `page` parameter is not provided, all assets are returned, without pagination information. The result will be a list of assets.
            - If a `page` parameter is provided, the response will be paginated, showing a specific number of assets per page as defined by `per_page` (default is 10).
            - If a search 'filter' such as 'solar "ACME corp"' is provided, the response will filter out assets where each search term is either present in their name or account name.
              The response schema for pagination is inspired by https://datatables.net/manual/server-side#Returned-data

        **Example response**

        An example of one account being returned:

        .. sourcecode:: json

        {
            "data" : [
                {
                    'id': 1,
                    'name': 'Test Account'
                    'account_roles': [1, 3],
                    'consultancy_account_id': 2,
                    'primary_color': '#1a3443'
                    'secondary_color': '#f1a122'
                    'logo_url': 'https://example.com/logo.png'
                }
            ],
            "num-records" : 1,
            "filtered-records" : 1

        }

        If no pagination is requested, the response only consists of the list under the "data" key.

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

        query = db.session.query(Account).filter(
            Account.id.in_([a.id for a in accounts])
        )

        if filter:
            search_terms = filter[0].split(" ")
            query = query.filter(
                or_(*[Account.name.ilike(f"%{term}%") for term in search_terms])
            )

        if sort_by is not None and sort_dir is not None:
            valid_sort_columns = {
                "id": Account.id,
                "name": Account.name,
                "assets": func.count(GenericAsset.id),
                "users": func.count(User.id),
            }

            query = query.join(GenericAsset, isouter=True).join(User, isouter=True)
            query = query.group_by(Account.id).order_by(
                valid_sort_columns[sort_by].asc()
                if sort_dir == "asc"
                else valid_sort_columns[sort_by].desc()
            )

        if page:
            select_pagination: SelectPagination = db.paginate(
                query, per_page=per_page, page=page
            )

            accounts_reponse: list = []
            for account in select_pagination.items:
                user_count_query = select(func.count(User.id)).where(
                    User.account_id == account.id
                )
                asset_count_query = select(func.count(GenericAsset.id)).where(
                    GenericAsset.account_id == account.id
                )
                user_count = db.session.execute(user_count_query).scalar()
                asset_count = db.session.execute(asset_count_query).scalar()
                accounts_reponse.append(
                    {
                        **account_schema.dump(account),
                        "user_count": user_count,
                        "asset_count": asset_count,
                    }
                )

            response = {
                "data": accounts_reponse,
                "num-records": select_pagination.total,
                "filtered-records": select_pagination.total,
            }
        else:
            response = accounts_schema.dump(query.all(), many=True)

        return response, 200

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
            if "consultancy_account_id" in account_data:
                return {
                    "errors": ["You are not allowed to update consultancy_account_id"]
                }, 401
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
        modified_fields = {
            field: getattr(account, field)
            for field in fields_to_check
            if account_data.get(field) != getattr(account, field)
        }

        # Compile modified fields string
        modified_fields_str = ", ".join(modified_fields.keys())

        for k, v in account_data.items():
            setattr(account, k, v)

        event_message = f"Account Updated, Field: {modified_fields_str}"

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
