from functools import wraps

from flask import current_app, abort
from marshmallow import ValidationError, validate, validates, fields
from sqlalchemy.exc import IntegrityError
from webargs.flaskparser import use_args
from flask_security import current_user
from flask_security.recoverable import send_reset_password_instructions
from flask_json import as_json
from pytz import all_timezones

from flexmeasures.data import ma
from flexmeasures.data.models.user import User as UserModel
from flexmeasures.data.services.users import (
    get_users,
    set_random_password,
    remove_cookie_and_token_access,
)
from flexmeasures.data.auth_setup import unauthorized_handler
from flexmeasures.api.common.responses import required_info_missing
from flexmeasures.data.config import db

"""
API endpoints to manage users.

Both POST (to create) and DELETE are not accessible via the API, but as CLI functions.
"""


class UserSchema(ma.SQLAlchemySchema):
    """
    This schema lists fields we support through this API (e.g. no password).
    """

    class Meta:
        model = UserModel

    @validates("timezone")
    def validate_timezone(self, timezone):
        if timezone not in all_timezones:
            raise ValidationError(f"Timezone {timezone} doesn't exist.")

    id = ma.auto_field()
    email = ma.auto_field(required=True, validate=validate.Email)
    username = ma.auto_field(required=True)
    active = ma.auto_field()
    timezone = ma.auto_field()
    flexmeasures_roles = ma.auto_field()


user_schema = UserSchema()
users_schema = UserSchema(many=True)


@use_args({"include_inactive": fields.Bool(missing=False)}, location="query")
@as_json
def get(args):
    """List all users."""
    users = get_users(only_active=not args["include_inactive"])
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
                    return unauthorized_handler(None, [])

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
        # Don't allow users who edit themselves to edit sensitive fields
        if current_user.id == db_user.id and k in ("active", "flexmeasures_roles"):
            return unauthorized_handler(None, [])
        setattr(db_user, k, v)
        if k == "active" and v is False:
            remove_cookie_and_token_access(db_user)
    db.session.add(db_user)
    try:
        db.session.commit()
    except IntegrityError as ie:
        return dict(message="Duplicate user already exists", detail=ie._message()), 400
    return user_schema.dump(db_user), 200


@load_user(admins_only=True)
@as_json
def reset_password(user):
    """
    Reset the user's current password, cookies and auth tokens.
    Send a password reset link to the user.
    """
    set_random_password(user)
    remove_cookie_and_token_access(user)
    send_reset_password_instructions(user)

    # commit only if sending instructions worked, as well
    db.session.commit()
