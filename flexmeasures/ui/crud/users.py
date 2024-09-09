from __future__ import annotations

from datetime import datetime

from flask import request, url_for
from flask_classful import FlaskView
from flask_security import login_required
from flask_wtf import FlaskForm
from wtforms import StringField, FloatField, DateTimeField, BooleanField
from wtforms.validators import DataRequired
from sqlalchemy import select

from flexmeasures.auth.policy import ADMIN_READER_ROLE, ADMIN_ROLE
from flexmeasures.auth.decorators import roles_required, roles_accepted
from flexmeasures.data import db
from flexmeasures.data.models.user import User, Role, Account
from flexmeasures.data.services.users import (
    get_user,
)
from flexmeasures.ui.utils.view_utils import render_flexmeasures_template
from flexmeasures.ui.crud.api_wrapper import InternalApi

"""
User Crud views for admins.

"""


class UserForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired()])
    username = StringField("Username", validators=[DataRequired()])
    roles = FloatField("Roles", validators=[DataRequired()])
    timezone = StringField("Timezone", validators=[DataRequired()])
    last_login_at = DateTimeField("Last Login was at", validators=[DataRequired()])
    active = BooleanField("Activation Status", validators=[DataRequired()])


def render_user(user: User | None, asset_count: int = 0, msg: str | None = None):
    user_form = UserForm()
    user_form.process(obj=user)
    return render_flexmeasures_template(
        "crud/user.html",
        user=user,
        user_form=user_form,
        asset_count=asset_count,
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


def get_users_by_account(
    account_id: int | str, include_inactive: bool = False
) -> list[User]:
    get_users_response = InternalApi().get(
        url_for(
            "UserAPI:index",
            account_id=account_id,
            include_inactive=include_inactive,
        )
    )
    users = [
        process_internal_api_response(user, make_obj=True)
        for user in get_users_response.json()
    ]
    return users


def get_all_users(include_inactive: bool = False) -> list[User]:
    get_users_response = InternalApi().get(
        url_for(
            "UserAPI:index",
            include_inactive=include_inactive,
        )
    )
    users = [
        process_internal_api_response(user, make_obj=True)
        for user in get_users_response.json()
    ]
    return users


class UserCrudUI(FlaskView):
    route_base = "/users"
    trailing_slash = False

    @login_required
    def index(self):
        """/users"""
        include_inactive = request.args.get("include_inactive", "0") != "0"
        users = get_all_users(include_inactive)

        return render_flexmeasures_template(
            "crud/users.html", users=users, include_inactive=include_inactive
        )

    @login_required
    @roles_accepted(ADMIN_ROLE, ADMIN_READER_ROLE)
    def get(self, id: str):
        """GET from /users/<id>"""
        get_user_response = InternalApi().get(url_for("UserAPI:get", id=id))
        user: User = process_internal_api_response(
            get_user_response.json(), make_obj=True
        )
        asset_count = 0
        if user:
            get_users_assets_response = InternalApi().get(
                url_for("AssetAPI:index", account_id=user.account_id)
            )
            asset_count = len(get_users_assets_response.json())
        return render_user(user, asset_count=asset_count)

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
            user,
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
        audit_log_response = InternalApi().get(url_for("UserAPI:auditlog", id=id))
        audit_logs_response = audit_log_response.json()
        return render_flexmeasures_template(
            "crud/user_audit_log.html",
            user=user,
            audit_logs=audit_logs_response,
        )
