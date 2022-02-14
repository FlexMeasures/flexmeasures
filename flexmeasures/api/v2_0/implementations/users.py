from marshmallow import fields
from sqlalchemy.exc import IntegrityError
from webargs.flaskparser import use_kwargs, use_args
from flask_security import current_user
from flask_security.recoverable import send_reset_password_instructions
from flask_json import as_json
from werkzeug.exceptions import Forbidden

from flexmeasures.data.models.user import User as UserModel, Account
from flexmeasures.api.common.schemas.users import AccountIdField, UserIdField
from flexmeasures.data.schemas.users import UserSchema
from flexmeasures.data.services.users import (
    get_users,
    set_random_password,
    remove_cookie_and_token_access,
)
from flexmeasures.auth.decorators import permission_required_for_context
from flexmeasures.data import db

"""
API endpoints to manage users.

Both POST (to create) and DELETE are not accessible via the API, but as CLI functions.
"""

user_schema = UserSchema()
users_schema = UserSchema(many=True)


@use_kwargs(
    {
        "account": AccountIdField(
            data_key="account_id", load_default=AccountIdField.load_current
        ),
        "include_inactive": fields.Bool(load_default=False),
    },
    location="query",
)
@permission_required_for_context("read", arg_name="account")
@as_json
def get(account: Account, include_inactive: bool = False):
    """List users of an account."""
    users = get_users(account_name=account.name, only_active=not include_inactive)
    return users_schema.dump(users), 200


@use_kwargs({"user": UserIdField(data_key="id")}, location="path")
@permission_required_for_context("read", arg_name="user")
@as_json
def fetch_one(user_id: int, user: UserModel):
    """Fetch a given user"""
    return user_schema.dump(user), 200


@use_args(UserSchema(partial=True))
@use_kwargs({"db_user": UserIdField(data_key="id")}, location="path")
@permission_required_for_context("update", arg_name="db_user")
@as_json
def patch(id: int, user_data: dict, db_user: UserModel):
    """Update a user given its identifier"""
    allowed_fields = ["email", "username", "active", "timezone", "flexmeasures_roles"]
    for k, v in [(k, v) for k, v in user_data.items() if k in allowed_fields]:
        if current_user.id == db_user.id and k in ("active", "flexmeasures_roles"):
            raise Forbidden(
                "Users who edit themselves cannot edit security-sensitive fields."
            )
        setattr(db_user, k, v)
        if k == "active" and v is False:
            remove_cookie_and_token_access(db_user)
    db.session.add(db_user)
    try:
        db.session.commit()
    except IntegrityError as ie:
        return dict(message="Duplicate user already exists", detail=ie._message()), 400
    return user_schema.dump(db_user), 200


@use_kwargs({"user": UserIdField(data_key="id")}, location="path")
@permission_required_for_context("update", arg_name="user")
@as_json
def reset_password(user_id: int, user: UserModel):
    """
    Reset the user's current password, cookies and auth tokens.
    Send a password reset link to the user.
    """
    set_random_password(user)
    remove_cookie_and_token_access(user)
    send_reset_password_instructions(user)

    # commit only if sending instructions worked, as well
    db.session.commit()
