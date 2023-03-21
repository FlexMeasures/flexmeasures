from __future__ import annotations

from flask import url_for
from flask_classful import FlaskView
from flexmeasures.ui.crud.api_wrapper import InternalApi
from flexmeasures.ui.utils.view_utils import render_flexmeasures_template


def get_accounts() -> list[dict]:
    """/accounts"""
    accounts = []
    accounts_response = InternalApi().get(url_for("AccountAPI:index"))
    accounts = accounts_response.json()

    return accounts


def get_account(account_id: str) -> dict:
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
        """/accounts/<account_id>"""
        account = get_account(account_id)
        return render_flexmeasures_template(
            "crud/account.html",
            account=account,
        )
