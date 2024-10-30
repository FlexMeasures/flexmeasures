from sqlalchemy import select
from werkzeug.exceptions import Forbidden, Unauthorized
from flask_security.core import current_user
from flask_security import login_required

from flexmeasures.auth.policy import check_access

from flexmeasures.data import db
from flexmeasures.data.models.audit_log import AuditLog
from flexmeasures.data.models.user import Account
from flexmeasures.ui.views import flexmeasures_ui
from flexmeasures.data.services.accounts import (
    get_number_of_assets_in_account,
    get_account_roles,
)
from flexmeasures.ui.utils.view_utils import render_flexmeasures_template


@flexmeasures_ui.route("/logged-in-user", methods=["GET"])
@login_required
def logged_in_user_view():
    """
    Basic information about the currently logged-in user.
    Plus basic actions (logout, reset pwd)
    """
    account_roles = get_account_roles(current_user.account_id)
    account_role_names = [account_role.name for account_role in account_roles]
    account = db.session.execute(
        select(Account).filter_by(id=current_user.account_id)
    ).scalar()

    user_can_view_account_auditlog = True
    try:
        check_access(AuditLog.account_table_acl(account), "read")
    except (Forbidden, Unauthorized):
        user_can_view_account_auditlog = False

    user_view_user_auditlog = True
    try:
        check_access(AuditLog.user_table_acl(current_user), "read")
    except (Forbidden, Unauthorized):
        user_view_user_auditlog = False

    return render_flexmeasures_template(
        "admin/logged_in_user.html",
        logged_in_user=current_user,
        roles=",".join([role.name for role in current_user.roles]),
        num_assets=get_number_of_assets_in_account(current_user.account_id),
        account_role_names=account_role_names,
        can_view_account_auditlog=user_can_view_account_auditlog,
        can_view_user_auditlog=user_view_user_auditlog,
    )
