import random
import string
from typing import Optional

from flask import request
from flask_classful import FlaskView
from flask_wtf import FlaskForm
from wtforms import StringField, FloatField, DateTimeField, BooleanField
from wtforms.validators import DataRequired
from flask_security import roles_required
from flask_security.recoverable import update_password, send_reset_password_instructions
from werkzeug.exceptions import NotFound

from bvp.data.models.user import User
from bvp.data.services.users import get_users, toggle_activation_status_of, delete_user
from bvp.ui.utils.view_utils import render_bvp_template

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


# Some helpers


def get_user(id: str) -> User:
    user: User = User.query.filter_by(id=int(id)).one_or_none()
    if user is None:
        raise NotFound
    return user


def render_user(user: Optional[User], msg: str = None):
    user_form = UserForm()
    user_form.process(obj=user)
    return render_bvp_template(
        "crud/user.html", user=user, user_form=user_form, msg=msg
    )


class UserCrud(FlaskView):
    route_base = "/users"
    trailing_slash = False

    @roles_required("admin")
    def index(self):
        """/users"""
        only_active = request.args.get("include_inactive", "0") == "0"
        users = get_users(only_active=only_active)
        return render_bvp_template(
            "crud/users.html", users=users, include_inactive=not only_active
        )

    @roles_required("admin")
    def get(self, id: str):
        """GET from /users/<id>"""
        user: User = get_user(id)
        return render_user(user)

    @roles_required("admin")
    def delete_with_data(self, id: str):
        """Delete via /users/delete_with_data/<id>"""
        user: User = get_user(id)
        username = user.username
        delete_user(user)
        return render_user(
            None,
            msg="User %s and assorted assets/readings have been deleted." % username,
        )

    @roles_required("admin")
    def toggle_active(self, id: str):
        """Toggle activation status via /users/toggle_active/<id>"""
        user: User = get_user(id)
        toggle_activation_status_of(user)
        return render_user(
            user,
            msg="User %s's new activation status is now %s."
            % (user.username, user.active),
        )

    @roles_required("admin")
    def reset_password_for(self, id: str):
        """/users/reset_password_for/<id>
        Set the password to something random (in case of worries the password might be compromised)
        and send instructions on how to reset."""
        user: User = get_user(id)
        new_random_password = "".join(
            [random.choice(string.ascii_lowercase) for _ in range(12)]
        )
        update_password(user, new_random_password)
        send_reset_password_instructions(user)
        return render_user(
            user,
            msg="The user's password has been changed to a random password"
            " and password reset instructions have been sent to the user.",
        )
