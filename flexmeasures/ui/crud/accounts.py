from __future__ import annotations

from sqlalchemy import select
from flask import request, url_for
from flask_classful import FlaskView
from flask_security import login_required
from flask_security.core import current_user

from flexmeasures.auth.policy import user_has_admin_access

from flexmeasures.ui.crud.api_wrapper import InternalApi
from flexmeasures.ui.utils.view_utils import render_flexmeasures_template
from flexmeasures.data.models.user import Account
from flexmeasures.data import db


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

        return render_flexmeasures_template(
            "crud/accounts.html",
        )

    @login_required
    def get(self, account_id: str):
        """/accounts/<account_id>"""
        include_inactive = request.args.get("include_inactive", "0") != "0"
        account = get_account(account_id)
        if account["consultancy_account_id"]:
            consultancy_account = db.session.execute(
                select(Account).filter_by(id=account["consultancy_account_id"])
            ).scalar_one_or_none()
            if consultancy_account:
                account["consultancy_account_name"] = consultancy_account.name
        accounts = get_accounts() if user_has_admin_access(current_user, "read") else []
        return render_flexmeasures_template(
            "crud/account.html",
            account=account,
            accounts=accounts,
            include_inactive=include_inactive,
        )

    @login_required
    def auditlog(self, account_id: str):
        """/accounts/auditlog/<account_id>"""
        account = get_account(account_id)
        audit_log_response = InternalApi().get(
            url_for("AccountAPI:auditlog", id=account_id)
        )
        audit_logs_response = audit_log_response.json()
        return render_flexmeasures_template(
            "crud/account_audit_log.html",
            audit_logs=audit_logs_response,
            account=account,
        )
