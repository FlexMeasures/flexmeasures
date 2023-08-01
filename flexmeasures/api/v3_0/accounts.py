from flask_classful import FlaskView, route
from webargs.flaskparser import use_kwargs
from flask_security import current_user, auth_required
from flask_json import as_json

from flexmeasures.auth.policy import user_has_admin_access
from flexmeasures.auth.decorators import permission_required_for_context
from flexmeasures.data.models.user import Account
from flexmeasures.data.services.accounts import get_accounts
from flexmeasures.api.common.schemas.users import AccountIdField
from flexmeasures.data.schemas.account import AccountSchema

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

    @route("", methods=["GET"])
    @auth_required("token", "session")
    @as_json
    def index(self):
        """API endpoint to list all accounts accessible to the current user.

        .. :quickref: Account; Download account list

        This endpoint returns all accessible accounts.
        Accessible accounts are your own account, or all accounts for admins.
        When the super-account concept (GH#203) lands, then users in such accounts see all managed accounts.

        **Example response**

        An example of one account being returned:

        .. sourcecode:: json

            [
                {
                    'id': 1,
                    'name': 'Test Account'
                    'account_roles': [1, 3],
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
            accounts = [current_user.account]
        return accounts_schema.dump(accounts), 200

    @route("/<id>", methods=["GET"])
    @use_kwargs({"account": AccountIdField(data_key="id")}, location="path")
    @permission_required_for_context("read", ctx_arg_name="account")
    @as_json
    def get(self, id: int, account: Account):
        """API endpoint to get an account.

        .. :quickref: Account; Get an account

        This endpoint retrieves an account, given its id.
        Only admins or the user themselves can use this endpoint.

        **Example response**

        .. sourcecode:: json

            {
                'id': 1,
                'name': 'Test Account'
                'account_roles': [1, 3],
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
