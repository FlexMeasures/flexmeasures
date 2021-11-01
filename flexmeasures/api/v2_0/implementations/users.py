from functools import wraps

from flask import current_app, abort
from marshmallow import fields
from sqlalchemy.exc import IntegrityError
from webargs.flaskparser import use_args
from flask_security import current_user
from flask_security.recoverable import send_reset_password_instructions
from flask_json import as_json
from werkzeug.exceptions import Forbidden

from flexmeasures.data.models.user import User as UserModel
from flexmeasures.data.schemas.users import UserSchema
from flexmeasures.data.services.users import (
    get_users,
    set_random_password,
    remove_cookie_and_token_access,
)
from flexmeasures.auth.policy import ADMIN_ROLE, ADMIN_READER_ROLE
from flexmeasures.api.common.responses import required_info_missing
from flexmeasures.data.config import db

"""
API endpoints to manage users.

Both POST (to create) and DELETE are not accessible via the API, but as CLI functions.
"""

user_schema = UserSchema()
users_schema = UserSchema(many=True)


@use_args(
    {
        "account_name": fields.Str(),
        "include_inactive": fields.Bool(missing=False),
    },
    location="query",
)
@as_json
def get(args):
    """List users. Defaults to users in non-admin's account."""

    user_is_admin = current_user.has_role(ADMIN_ROLE) or current_user.has_role(
        ADMIN_READER_ROLE
    )
    account_name = args.get("account_name", None)

    if account_name is None and not user_is_admin:
        account_name = current_user.account.name
    if (
        account_name is not None
        and account_name != current_user.account.name
        and not user_is_admin
    ):
        raise Forbidden(
            f"User {current_user.username} cannot list users from account {account_name}."
        )
    users = get_users(
        account_name=account_name, only_active=not args["include_inactive"]
    )
    return users_schema.dump(users), 200


def load_user(admins_only: bool = False):
    """Decorator which loads a user by the Id expected in the path.
    Raises 400 if that is not possible due to wrong parameters.
    Raises 404 if user is not found.
    Raises 403 if unauthorized:
    Only the user themselves or admins can access a user object.
    The admins_only parameter can be used if not even the user themselves
    should be allowed.

        @app.route('/user/<id>')
        @check_user
        def get_user(user):
            return user_schema.dump(user), 200

    The route must specify one parameter ― id.
    """

    def wrapper(fn):
        @wraps(fn)
        @as_json
        def decorated_endpoint(*args, **kwargs):

            args = list(args)
            if len(args) == 0:
                current_app.logger.warning("Request missing id.")
                return required_info_missing(["id"])
            if len(args) > 1:
                return (
                    dict(
                        status="UNEXPECTED_PARAMS",
                        message="Only expected one parameter (id).",
                    ),
                    400,
                )

            try:
                id = int(args[0])
            except ValueError:
                current_app.logger.warning("Cannot parse ID argument from request.")
                return required_info_missing(["id"], "Cannot parse ID arg as int.")

            user: UserModel = UserModel.query.filter_by(id=int(id)).one_or_none()

            if user is None:
                raise abort(404, f"User {id} not found")

            if not current_user.has_role("admin"):
                if admins_only or user != current_user:
                    raise Forbidden("Needs to be admin or the current user.")

            args = (user,)
            return fn(*args, **kwargs)

        return decorated_endpoint

    return wrapper


@load_user()
@as_json
def fetch_one(user: UserModel):
    """Fetch a given user"""
    return user_schema.dump(user), 200


@load_user()
@use_args(UserSchema(partial=True))
@as_json
def patch(db_user: UserModel, user_data: dict):
    """Update a user given its identifier"""
    allowed_fields = ["email", "username", "active", "timezone", "flexmeasures_roles"]
    for k, v in [(k, v) for k, v in user_data.items() if k in allowed_fields]:
        if current_user.id == db_user.id and k in ("active", "flexmeasures_roles"):
            raise Forbidden("Users who edit themselves cannot edit sensitive fields.")
        setattr(db_user, k, v)
        if k == "active" and v is False:
            remove_cookie_and_token_access(db_user)
    db.session.add(db_user)
    try:
        db.session.commit()
    except IntegrityError as ie:
        return dict(message="Duplicate user already exists", detail=ie._message()), 400
    return user_schema.dump(db_user), 200


@load_user()
@as_json
def reset_password(user):
    """
    Reset the user's current password, cookies and auth tokens.
    Send a password reset link to the user.
    """
    if current_user.id != user.id and not current_user.has_role("admin"):
        raise Forbidden("Non-admins cannot reset passwords of other users.")
    set_random_password(user)
    remove_cookie_and_token_access(user)
    send_reset_password_instructions(user)

    # commit only if sending instructions worked, as well
    db.session.commit()
