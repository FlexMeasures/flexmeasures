from __future__ import annotations

from flask_classful import FlaskView, route
from flexmeasures.data import db
from webargs.flaskparser import use_kwargs, use_args
from flask_security import current_user, auth_required
from flask_json import as_json
from sqlalchemy import or_, select, func
from flask_sqlalchemy.pagination import SelectPagination


from flexmeasures.auth.policy import user_has_admin_access
from flexmeasures.auth.decorators import permission_required_for_context
from flexmeasures.data.models.audit_log import AuditLog
from flexmeasures.data.models.user import Account, User
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.services.accounts import get_accounts, get_audit_log_records
from flexmeasures.api.common.schemas.users import AccountIdField
from flexmeasures.data.schemas.account import AccountSchema
from flexmeasures.utils.time_utils import server_now
from flexmeasures.api.common.schemas.users import AccountAPIQuerySchema

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
    @use_kwargs(AccountAPIQuerySchema, location="query")
    @as_json
    def index(
        self,
        page: int | None = None,
        per_page: int | None = None,
        filter: list[str] | None = None,
        sort_by: str | None = None,
        sort_dir: str | None = None,
    ):
        """
        .. :quickref: Accounts; List all accounts accessible to the current user.
        ---
        get:
          summary: List all accounts accessible to the current user.
          description: |
            This endpoint returns all accounts the current user has access to.
            Accessible accounts include the user's own account, accounts for which the user is a consultant, and all accounts if the user has admin privileges.

            The endpoint supports pagination of the account list using the `page` and `per_page` query parameters.
              - If the `page` parameter is not provided, all accounts are returned, without pagination information. The result will be a list of accounts.
              - If a `page` parameter is provided, the response will be paginated, showing a specific number of accounts per page as defined by `per_page` (default is 10).
              - If a search 'filter' such as 'solar "ACME corp"' is provided, the response will filter out accounts where each search term is either present in their name.
              The response schema for pagination is inspired by [DataTables](https://datatables.net/manual/server-side#Returned-data)

          security:
            - ApiKeyAuth: []
          parameters:
            - in: query
              schema: AccountAPIQuerySchema
          responses:
            200:
              description: PROCESSED
              content:
                application/json:
                  examples:
                    single_account:
                      summary: One account being returned (no pagination requested)
                      value:
                        - id: 1
                          name: Test Account
                          account_roles: [1, 3]
                          consultancy_account_id: 2
                          primary_color: '#1a3443'
                          secondary_color: '#f1a122'
                          logo_url: 'https://example.com/logo.png'
                    paginated_accounts:
                      summary: A paginated list of accounts being returned
                      value:
                        data:
                          - id: 1
                            name: Test Account
                            account_roles: [1, 3]
                            consultancy_account_id: 2
                            primary_color: '#1a3443'
                            secondary_color: '#f1a122'
                            logo_url: 'https://example.com/logo.png'
                        num-records: 1
                        filtered-records: 1
            400:
              description: INVALID_REQUEST
            401:
              description: UNAUTHORIZED
            403:
              description: INVALID_SENDER
            422:
              description: UNPROCESSABLE_ENTITY
          tags:
            - Accounts
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
        """
        .. :quickref: Accounts; Fetch a given account.
        ---
        get:
          summary: Fetch one account.
          description: |
            This endpoint retrieves a single account, given its ID in the path.
            Access is restricted: only admins, consultants, and users belonging to the account itself are authorized to use this endpoint.

          security:
            - ApiKeyAuth: []
          parameters:
            - name: id
              in: path
              description: The ID of the account to retrieve.
              required: true
              schema:
                type: integer
                format: int32
          responses:
            200:
              description: PROCESSED
              content:
                application/json:
                  example:
                    id: 1
                    name: Test Account
                    account_roles: [1, 3]
                    consultancy_account_id: 2
            400:
              description: INVALID_REQUEST, REQUIRED_INFO_MISSING, or UNEXPECTED_PARAMS
            401:
              description: UNAUTHORIZED
            403:
              description: INVALID_SENDER
            422:
              description: UNPROCESSABLE_ENTITY
          tags:
            - Accounts
        """

        return account_schema.dump(account), 200

    @route("/<id>", methods=["PATCH"])
    @use_args(partial_account_schema)
    @use_kwargs({"account": AccountIdField(data_key="id")}, location="path")
    @permission_required_for_context("update", ctx_arg_name="account")
    @as_json
    def patch(self, account_data: dict, id: int, account: Account):
        """
        .. :quickref: Accounts; Update an account.
        ---
        patch:
          summary: Update an existing account.
          description: |
            This endpoint updates the details for an existing account.

            In the JSON body, sent in only the fields you want to update.

            **Restrictions on Fields:**
            - The **id** field is read-only and cannot be updated.
            - The **consultancy_account_id** field can only be edited if the current user has an **admin** role.

          security:
            - ApiKeyAuth: []
          parameters:
            - name: id
              in: path
              description: The ID of the account to update.
              required: true
              schema:
                type: integer
                format: int32
          requestBody:
            description: Account data to be updated.
            required: true
            content:
              application/json:
                schema: AccountSchema
                example:
                  name: Test Account Updated
                  primary_color: '#1a3443'
                  secondary_color: '#f1a122'
                  logo_url: 'https://example.com/logo.png'
                  consultancy_account_id: 2
          responses:
            200:
              description: UPDATED (The entire updated account object is returned)
              content:
                application/json:
                  example:
                    id: 1
                    name: Test Account Updated
                    account_roles: [1, 3]
                    primary_color: '#1a3443'
                    secondary_color: '#f1a122'
                    logo_url: 'https://example.com/logo.png'
                    consultancy_account_id: 2
            400:
              description: INVALID_REQUEST, REQUIRED_INFO_MISSING, or UNEXPECTED_PARAMS
            401:
              description: UNAUTHORIZED
            403:
              description: INVALID_SENDER
            422:
              description: UNPROCESSABLE_ENTITY (e.g., trying to update 'consultancy_account_id' without admin rights)
          tags:
            - Accounts
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
        """
        .. :quickref: Accounts; Get the history of actions for a specific account.
        ---
        get:
          summary: Get the history of actions for a specific account.
          description: |
            This endpoint retrieves a log of historical actions and events associated with the account, identified by its ID.

          security:
            - ApiKeyAuth: []
          parameters:
            - name: id
              in: path
              description: The ID of the account whose history is being requested.
              required: true
              schema:
                type: integer
                format: int32
          responses:
            200:
              description: PROCESSED
              content:
                application/json:
                  schema:
                    type: array
                    items:
                      type: object
                      properties:
                        event:
                          type: string
                          description: Description of the action or event that occurred.
                        event_datetime:
                          type: string
                          format: date-time
                          description: Timestamp when the event occurred.
                        active_user_id:
                          type: integer
                          description: The ID of the user who performed the action.
                  examples:
                    account_history_list:
                      summary: A list of account history events
                      value:
                        - event: 'User test user deleted'
                          event_datetime: '2021-01-01T00:00:00'
                          active_user_id: 1
                        - event: 'Account name changed to "New Corp"'
                          event_datetime: '2021-01-02T10:30:00'
                          active_user_id: 5
            400:
              description: INVALID_REQUEST, REQUIRED_INFO_MISSING, or UNEXPECTED_PARAMS
            401:
              description: UNAUTHORIZED
            403:
              description: INVALID_SENDER
            422:
              description: UNPROCESSABLE_ENTITY
          tags:
            - Accounts
        """
        audit_logs = get_audit_log_records(account)
        audit_logs = [
            {k: getattr(log, k) for k in ("event", "event_datetime", "active_user_id")}
            for log in audit_logs
        ]
        return audit_logs, 200
