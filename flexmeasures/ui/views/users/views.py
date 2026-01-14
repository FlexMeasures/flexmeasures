from __future__ import annotations

from flask import request
from flask_classful import FlaskView
from flask_security.core import current_user
from flask_security import login_required
from werkzeug.exceptions import Forbidden, Unauthorized
from sqlalchemy import select

from flexmeasures.auth.policy import check_access
from flexmeasures.data import db
from flexmeasures.data.models.audit_log import AuditLog
from flexmeasures.data.models.user import User, Role, Account
from flexmeasures.data.services.users import (
    get_user_by_id_or_raise_notfound,
    reset_password,
)
from flexmeasures.ui.utils.view_utils import render_flexmeasures_template

"""
User Crud views for admins and consultants.
"""


def render_user(user: User | None, msg: str | None = None):
    """Renders the user details page."""
    user_view_user_auditlog = True
    try:
        check_access(AuditLog.user_table_acl(current_user), "read")
    except (Forbidden, Unauthorized):
        user_view_user_auditlog = False

    can_edit_user_details = True
    try:
        check_access(user, "update")
    except (Forbidden, Unauthorized):
        can_edit_user_details = False

    roles = {}
    for role in db.session.scalars(select(Role)).all():
        roles[role.name] = role.id

    user_roles = []
    if user is not None:
        user_roles = [role.name for role in user.flexmeasures_roles]

    return render_flexmeasures_template(
        "users/user.html",
        can_view_user_auditlog=user_view_user_auditlog,
        can_edit_user_details=can_edit_user_details,
        user=user,
        user_roles=user_roles,
        roles=roles,
        asset_count=user.account.number_of_assets,
        msg=msg,
    )


class UserCrudUI(FlaskView):
    route_base = "/users"
    trailing_slash = False

    @login_required
    def index(self):
        """/users"""
        include_inactive = request.args.get("include_inactive", "0") != "0"
        accounts = db.session.scalars(select(Account).order_by(Account.name)).all()
        return render_flexmeasures_template(
            "users/users.html", include_inactive=include_inactive, accounts=accounts
        )

    @login_required
    def get(self, id: str):
        """GET from /users/<id>"""
        user: User = get_user_by_id_or_raise_notfound(id)
        check_access(user, "read")
        return render_user(user)

    @login_required
    def reset_password_for(self, id: str):
        """/users/reset_password_for/<id>
        Set the password to something random (in case of worries the password might be compromised)
        and send instructions on how to reset."""
        user: User = get_user_by_id_or_raise_notfound(id)
        check_access(user, "update")
        reset_password(user)
        db.session.commit()
        return render_user(
            user,
            msg="The user's password has been changed to a random password"
            " and password reset instructions have been sent to the user."
            " Cookies and the API access token have also been invalidated.",
        )

    @login_required
    def auditlog(self, id: str):
        """/users/auditlog/<id>
        View all user actions.
        """
        user: User = get_user_by_id_or_raise_notfound(id)
        return render_flexmeasures_template(
            "users/user_audit_log.html",
            user=user,
        )
