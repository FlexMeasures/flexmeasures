from flask import url_for
from flask_classful import FlaskView
from flask_login import current_user
from flexmeasures.ui.crud.api_wrapper import InternalApi

from flexmeasures.auth.policy import ADMIN_READER_ROLE, ADMIN_ROLE
from flexmeasures.ui.utils.view_utils import render_flexmeasures_template


def get_accounts():
    """/accounts"""
    accounts = []
    if current_user.has_role(ADMIN_ROLE) or current_user.has_role(ADMIN_READER_ROLE):
        accounts_response = InternalApi().get(url_for("AccountAPI:index"))
        accounts = accounts_response.json()
    else:
        accounts = [
            {
                "id": current_user.user_account.id,
                "name": current_user.account.name,
                "account_roles": [
                    current_user.account.account_roles[i].id
                    for i in current_user.account.account_roles
                ],
            }
        ]

    return accounts


def get_account(account_id: str):
    account_response = InternalApi().get(url_for("AccountAPI:get", id=account_id))
    account = account_response.json()

    return account


class AccountCrudUI(FlaskView):
    route_base = "/accounts"
    trailing_slash = False

    def index(self):
        """/accounts"""
        accounts = get_accounts()

        return render_flexmeasures_template(
            "crud/accounts.html",
            accounts=accounts,
        )

    def get(self, account_id: str):
        account = get_account(account_id)
        return render_flexmeasures_template(
            "crud/account.html",
            account=account,
        )
