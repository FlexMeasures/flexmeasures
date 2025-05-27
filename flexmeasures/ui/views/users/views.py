from __future__ import annotations

from datetime import datetime

from flask import request, url_for
from flask_classful import FlaskView
from flask_security.core import current_user
from flask_security import login_required
from werkzeug.exceptions import Forbidden, Unauthorized
from sqlalchemy import select

from flexmeasures.auth.policy import ADMIN_READER_ROLE, ADMIN_ROLE, check_access
from flexmeasures.auth.decorators import roles_required, roles_accepted
from flexmeasures.data import db
from flexmeasures.data.models.audit_log import AuditLog
from flexmeasures.data.models.user import User, Role, Account
from flexmeasures.data.services.users import (
    get_user,
)
from flexmeasures.ui.utils.view_utils import render_flexmeasures_template
from flexmeasures.ui.views.api_wrapper import InternalApi

"""
User Crud views for admins.

"""


def render_user(user: User | None, msg: str | None = None):

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


def process_internal_api_response(
    user_data: dict, user_id: int | None = None, make_obj=False
) -> User | dict:
    """
    Turn data from the internal API into something we can use to further populate the UI.
    Either as a user object or a dict for form filling.
    """
    with db.session.no_autoflush:
        role_ids = tuple(user_data.get("flexmeasures_roles", []))
        user_data["flexmeasures_roles"] = db.session.scalars(
            select(Role).filter(Role.id.in_(role_ids))
        ).all()
        user_data.pop("status", None)  # might have come from requests.response
        for date_field in ("last_login_at", "last_seen_at"):
            if date_field in user_data and user_data[date_field] is not None:
                user_data[date_field] = datetime.fromisoformat(user_data[date_field])
        if user_id:
            user_data["id"] = user_id
        if make_obj:
            user = User(**user_data)
            user.account = db.session.get(Account, user_data.get("account_id", -1))
            if user in db.session:
                db.session.expunge(user)
            return user
    return user_data


def get_all_users(include_inactive: bool = False) -> list[User]:
    get_users_response = InternalApi().get(
        url_for(
            "UserAPI:index",
            include_inactive=include_inactive,
        )
    )
    users = [user for user in get_users_response.json()]
    return users


class UserCrudUI(FlaskView):
    route_base = "/users"
    trailing_slash = False

    @login_required
    def index(self):
        """/users"""
        include_inactive = request.args.get("include_inactive", "0") != "0"
        return render_flexmeasures_template(
            "users/users.html", include_inactive=include_inactive
        )

    @login_required
    @roles_accepted(ADMIN_ROLE, ADMIN_READER_ROLE)
    def get(self, id: str):
        """GET from /users/<id>"""
        get_user_response = InternalApi().get(url_for("UserAPI:get", id=id))
        user: User = process_internal_api_response(
            get_user_response.json(), make_obj=True
        )
        return render_user(user)

    @roles_required(ADMIN_ROLE)
    def toggle_active(self, id: str):
        """Toggle activation status via /users/toggle_active/<id>"""
        user: User = get_user(id)
        user_response = InternalApi().patch(
            url_for("UserAPI:patch", id=id),
            args={"active": not user.active},
        )
        patched_user: User = process_internal_api_response(
            user_response.json(), make_obj=True
        )
        return render_user(
            patched_user,
            msg="User %s's new activation status is now %s."
            % (patched_user.username, patched_user.active),
        )

    @login_required
    def reset_password_for(self, id: str):
        """/users/reset_password_for/<id>
        Set the password to something random (in case of worries the password might be compromised)
        and send instructions on how to reset."""
        user: User = get_user(id)
        InternalApi().patch(
            url_for("UserAPI:reset_user_password", id=id),
        )
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
        user: User = get_user(id)
        return render_flexmeasures_template(
            "users/user_audit_log.html",
            user=user,
        )
