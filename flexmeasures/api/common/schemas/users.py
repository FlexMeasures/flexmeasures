from typing import Any

from flask import abort
from flask_security import current_user
from marshmallow import fields, validate
from sqlalchemy import select

from flexmeasures.data import db
from flexmeasures.data.models.user import User, Account
from flexmeasures.api.common.schemas.generic_schemas import PaginationSchema


class AccountIdField(fields.Integer):
    """
    Field that represents an account ID. It deserializes from the account id to an account instance.
    """

    def _deserialize(self, value: Any, attr, data, **kwargs) -> Account:
        account_id: int = super()._deserialize(value, attr, data, **kwargs)
        account: Account = db.session.execute(
            select(Account).filter_by(id=account_id)
        ).scalar_one_or_none()
        if account is None:
            raise abort(404, f"Account {account_id} not found")
        return account

    def _serialize(self, value: Account, attr, obj, **kwargs) -> int:
        return value.id

    @classmethod
    def load_current(cls):
        """
        Use this with the load_default arg to __init__ if you want the current user's account
        by default.
        """
        return current_user.account if not current_user.is_anonymous else None


class UserIdField(fields.Integer):
    """
    Field that represents a user ID. It deserializes from the user id to a user instance.
    """

    def __init__(self, *args, **kwargs):
        kwargs["load_default"] = lambda: (
            current_user if not current_user.is_anonymous else None
        )
        super().__init__(*args, **kwargs)

    def _deserialize(self, value: Any, attr, data, **kwargs) -> User:
        user_id: int = super()._deserialize(value, attr, data, **kwargs)
        user: User = db.session.execute(
            select(User).filter_by(id=user_id)
        ).scalar_one_or_none()
        if user is None:
            raise abort(404, f"User {user_id} not found")
        return user

    def _serialize(self, value: User, attr, obj, **kwargs) -> int:
        return value.id


class AccountAPIQuerySchema(PaginationSchema):
    sort_by = fields.Str(
        required=False,
        validate=validate.OneOf(["id", "name", "assets", "users"]),
    )
