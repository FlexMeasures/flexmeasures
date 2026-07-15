from __future__ import annotations

from flask import request
from sqlalchemy import or_, select
from werkzeug.exceptions import Forbidden, Unauthorized, NotFound
from flask_classful import FlaskView, route
from flask_security import login_required
from flask_security.core import current_user

from flexmeasures.auth.policy import (
    user_can_add_accounts,
    user_has_admin_access,
    check_access,
    FlexMeasuresPlatform,
)

from flexmeasures.ui.utils.view_utils import render_flexmeasures_template, ICON_MAPPING
from flexmeasures.ui.utils.breadcrumb_utils import get_breadcrumb_info
from flexmeasures.data.models.audit_log import AuditLog
from flexmeasures.data.models.user import Account, AccountRole, Plan
from flexmeasures.data.services.accounts import get_accounts, get_audit_log_records
from flexmeasures.data import db
from flexmeasures.ui.views import (
    ATTRIBUTES_FIELD_LABEL,
    ATTRIBUTES_FIELD_DESCRIPTION,
)
from flexmeasures.utils.secrets_utils import get_secret_overview


class AccountCrudUI(FlaskView):
    route_base = "/accounts"
    trailing_slash = False

    @login_required
    def index(self):
        """/accounts"""

        user_can_create_account = user_can_add_accounts()

        return render_flexmeasures_template(
            "accounts/accounts.html",
            user_can_create_account=user_can_create_account,
        )

    @route("/new", methods=["GET"])
    @login_required
    def new(self):
        """/accounts/new"""
        check_access(FlexMeasuresPlatform.init(), "create-children")
        user_is_admin = user_has_admin_access(current_user, "read")
        potential_consultant_accounts = get_accounts() if user_is_admin else []
        selected_consultancy_account_id = request.args.get(
            "consultancy_account_id", default=None, type=int
        )
        selected_consultancy_account_name = None
        if user_is_admin and selected_consultancy_account_id is not None:
            selected_consultancy_account = db.session.get(
                Account, selected_consultancy_account_id
            )
            if selected_consultancy_account is not None:
                selected_consultancy_account_name = selected_consultancy_account.name
        elif not user_is_admin:
            selected_consultancy_account_name = current_user.account.name
        return render_flexmeasures_template(
            "accounts/account_create.html",
            user_is_admin=user_is_admin,
            accounts=potential_consultant_accounts,
            selected_consultancy_account_id=selected_consultancy_account_id,
            selected_consultancy_account_name=selected_consultancy_account_name,
        )

    @login_required
    def get(self, account_id: str):
        """/accounts/<account_id>"""
        account = db.session.execute(select(Account).filter_by(id=account_id)).scalar()
        if account is None:
            raise NotFound(f"Account with id {account_id} not found.")
        check_access(account, "read")
        if account.consultancy_account_id:
            consultancy_account = db.session.execute(
                select(Account).filter_by(id=account.consultancy_account_id)
            ).scalar_one_or_none()
            if consultancy_account:
                account.consultancy_account.name = consultancy_account.name
        # admins can set all accounts as admins, others cannot set any
        potential_consultant_accounts = (
            get_accounts() if user_has_admin_access(current_user, "read") else []
        )
        # Only admins get to assign a plan, and only a plan we still hand out
        # (or the legacy plan the account happens to be on already)
        assignable_plans = (
            db.session.scalars(
                select(Plan)
                .filter(or_(Plan.legacy.is_(False), Plan.id == account.plan_id))
                .order_by(Plan.name)
            ).all()
            if user_has_admin_access(current_user, "read")
            else []
        )

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

        user_is_admin = user_has_admin_access(current_user, "read")
        can_add_client_account = user_can_add_accounts() and (
            user_is_admin or account.id == current_user.account.id
        )

        account_role_options = {
            role.name: role.id for role in db.session.scalars(select(AccountRole)).all()
        }
        selected_account_roles = [role.name for role in account.account_roles]

        return render_flexmeasures_template(
            "accounts/account.html",
            account=account,
            accounts=potential_consultant_accounts,
            plans=assignable_plans,
            user_is_admin=user_is_admin,
            can_add_client_account=can_add_client_account,
            account_role_options=account_role_options,
            selected_account_roles=selected_account_roles,
            user_can_update_account=user_can_update_account,
            user_can_create_children=user_can_create_children,
            can_view_account_auditlog=user_can_view_account_auditlog,
            asset_icon_map=ICON_MAPPING,
            attributes_label=ATTRIBUTES_FIELD_LABEL,
            attributes_description=ATTRIBUTES_FIELD_DESCRIPTION,
            stored_secrets=get_secret_overview(account.secrets),
            breadcrumb_info=get_breadcrumb_info(account),
        )

    @login_required
    def auditlog(self, account_id: str):
        """/accounts/auditlog/<account_id>"""
        account = db.session.execute(select(Account).filter_by(id=account_id)).scalar()
        check_access(account, "read")

        audit_logs = get_audit_log_records(account)

        return render_flexmeasures_template(
            "accounts/account_audit_log.html",
            audit_logs=audit_logs,
            account=account,
        )
