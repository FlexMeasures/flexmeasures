from typing import Optional, Union

from flask import request, url_for
from flask_classful import FlaskView
from flask_wtf import FlaskForm
from wtforms import StringField, FloatField, DateTimeField, BooleanField
from wtforms.validators import DataRequired
from flask_security import roles_required

from flexmeasures.data.config import db
from flexmeasures.data.models.user import User, Role
from flexmeasures.data.services.users import (
    get_user,
)
from flexmeasures.ui.utils.view_utils import render_flexmeasures_template
from flexmeasures.ui.crud.api_wrapper import InternalApi

"""
User Crud views for admins.

Note: This uses the internal API 2.0 ― if these endpoints get updated in a later version,
      we should change the version here.
"""


class UserForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired()])
    username = StringField("Username", validators=[DataRequired()])
    roles = FloatField("Roles", validators=[DataRequired()])
    timezone = StringField("Timezone", validators=[DataRequired()])
    last_login_at = DateTimeField("Last Login was at", validators=[DataRequired()])
    active = BooleanField("Activation Status", validators=[DataRequired()])


def render_user(user: Optional[User], asset_count: int = 0, msg: str = None):
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
    user_data: dict, user_id: Optional[int] = None, make_obj=False
) -> Union[User, dict]:
    """
    Turn data from the internal API into something we can use to further populate the UI.
    Either as a user object or a dict for form filling.
    """
    with db.session.no_autoflush:
        role_ids = tuple(user_data.get("flexmeasures_roles", []))
        user_data["flexmeasures_roles"] = Role.query.filter(Role.id.in_(role_ids)).all()
        user_data.pop("status", None)  # might have come from requests.response
        if user_id:
            user_data["id"] = user_id
        if make_obj:
            user = User(**user_data)
            if user in db.session:
                db.session.expunge(user)
            return user
    return user_data


class UserCrudUI(FlaskView):
    route_base = "/users"
    trailing_slash = False

    @roles_required("admin")
    def index(self):
        """/users"""
        include_inactive = request.args.get("include_inactive", "0") != "0"
        get_users_response = InternalApi().get(
            url_for(
                "flexmeasures_api_v2_0.get_users", include_inactive=include_inactive
            )
        )
        users = [
            process_internal_api_response(user, make_obj=True)
            for user in get_users_response.json()
        ]
        return render_flexmeasures_template(
            "crud/users.html", users=users, include_inactive=include_inactive
        )

    @roles_required("admin")
    def get(self, id: str):
        """GET from /users/<id>"""
        get_user_response = InternalApi().get(
            url_for("flexmeasures_api_v2_0.get_user", id=id)
        )
        user: User = process_internal_api_response(
            get_user_response.json(), make_obj=True
        )
        asset_count = 0
        if user:
            get_users_assets_response = InternalApi().get(
                url_for("flexmeasures_api_v2_0.get_assets", owner_id=user.id)
            )
            asset_count = len(get_users_assets_response.json())
        return render_user(user, asset_count=asset_count)

    @roles_required("admin")
    def toggle_active(self, id: str):
        """Toggle activation status via /users/toggle_active/<id>"""
        user: User = get_user(id)
        user_response = InternalApi().patch(
            url_for("flexmeasures_api_v2_0.patch_user", id=id),
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

    @roles_required("admin")
    def reset_password_for(self, id: str):
        """/users/reset_password_for/<id>
        Set the password to something random (in case of worries the password might be compromised)
        and send instructions on how to reset."""
        user: User = get_user(id)
        InternalApi().patch(
            url_for("flexmeasures_api_v2_0.reset_user_password", id=id),
        )
        return render_user(
            user,
            msg="The user's password has been changed to a random password"
            " and password reset instructions have been sent to the user.",
        )
