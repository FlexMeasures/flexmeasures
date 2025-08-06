from __future__ import annotations

from sqlalchemy import select
from werkzeug.exceptions import Forbidden, Unauthorized
from flask import request, url_for
from flask_classful import FlaskView
from flask_security import login_required
from flask_security.core import current_user

from flexmeasures.auth.policy import user_has_admin_access, check_access

from flexmeasures.ui.views.api_wrapper import InternalApi
from flexmeasures.ui.utils.view_utils import render_flexmeasures_template
from flexmeasures.data.models.audit_log import AuditLog
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
            "accounts/accounts.html",
        )

    @login_required
    def get(self, account_id: str):
        """/accounts/<account_id>"""
        include_inactive = request.args.get("include_inactive", "0") != "0"
        account = db.session.execute(select(Account).filter_by(id=account_id)).scalar()
        if account.consultancy_account_id:
            consultancy_account = db.session.execute(
                select(Account).filter_by(id=account.consultancy_account_id)
            ).scalar_one_or_none()
            if consultancy_account:
                account.consultancy_account.name = consultancy_account.name
        accounts = get_accounts() if user_has_admin_access(current_user, "read") else []

        user_can_view_account_auditlog = True
        try:
            check_access(AuditLog.account_table_acl(account), "read")
        except (Forbidden, Unauthorized):
            user_can_view_account_auditlog = False

        user_can_update_account = True
        try:
            check_access(account, "update")
        except (Forbidden, Unauthorized):
            user_can_update_account = False

        user_can_create_children = True
        try:
            check_access(account, "create-children")
        except (Forbidden, Unauthorized):
            user_can_create_children = False

        return render_flexmeasures_template(
            "accounts/account.html",
            account=account,
            accounts=accounts,
            include_inactive=include_inactive,
            user_can_update_account=user_can_update_account,
            user_can_create_children=user_can_create_children,
            can_view_account_auditlog=user_can_view_account_auditlog,
        )

    @login_required
    def auditlog(self, account_id: str):
        """/accounts/auditlog/<account_id>"""
        account = db.session.execute(select(Account).filter_by(id=account_id)).scalar()
        audit_log_response = InternalApi().get(
            url_for("AccountAPI:auditlog", id=account_id)
        )
        audit_logs_response = audit_log_response.json()

        return render_flexmeasures_template(
            "accounts/account_audit_log.html",
            audit_logs=audit_logs_response,
            account=account,
        )
