from __future__ import annotations

from flask import request, url_for
from flask_classful import FlaskView
from flask_security import login_required
from flexmeasures.ui.crud.api_wrapper import InternalApi
from flexmeasures.ui.utils.view_utils import render_flexmeasures_template
from flexmeasures.ui.crud.assets import get_assets_by_account
from flexmeasures.ui.crud.users import get_users_by_account


def get_accounts() -> list[dict]:
    """/accounts"""
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

    @login_required
    def index(self):
        """/accounts"""
        accounts = get_accounts()
        for account in accounts:
            account["asset_count"] = len(get_assets_by_account(account["id"]))
            account["user_count"] = len(get_users_by_account(account["id"]))

        return render_flexmeasures_template(
            "crud/accounts.html",
            accounts=accounts,
        )

    @login_required
    def get(self, account_id: str):
        """/accounts/<account_id>"""
        include_inactive = request.args.get("include_inactive", "0") != "0"
        account = get_account(account_id)
        assets = get_assets_by_account(account_id)
        assets += get_assets_by_account(account_id=None)
        users = get_users_by_account(account_id, include_inactive=include_inactive)
        return render_flexmeasures_template(
            "crud/account.html",
            account=account,
            assets=assets,
            users=users,
            include_inactive=include_inactive,
        )
