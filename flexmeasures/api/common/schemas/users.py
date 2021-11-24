from flask import abort
from flask_security import current_user
from marshmallow import fields

from flexmeasures.data.models.user import User, Account


class AccountIdField(fields.Integer):
    """
    Field that represents an account ID. It de-serializes from the account id to an account instance.
    """

    def __init__(self, *args, **kwargs):
        kwargs["load_default"] = (
            lambda: current_user.account if not current_user.is_anonymous else None
        )
        super().__init__(*args, **kwargs)

    def _deserialize(self, account_id: int, attr, obj, **kwargs) -> Account:
        account: Account = Account.query.filter_by(id=int(account_id)).one_or_none()
        if account is None:
            raise abort(404, f"Account {id} not found")
        return account

    def _serialize(self, account: Account, attr, data, **kwargs) -> int:
        return account.id


class UserIdField(fields.Integer):
    """
    Field that represents a user ID. It de-serializes from the user id to a user instance.
    """

    def __init__(self, *args, **kwargs):
        kwargs["load_default"] = (
            lambda: current_user if not current_user.is_anonymous else None
        )
        super().__init__(*args, **kwargs)

    def _deserialize(self, user_id: int, attr, obj, **kwargs) -> User:
        user: User = User.query.filter_by(id=int(user_id)).one_or_none()
        if user is None:
            raise abort(404, f"User {id} not found")
        return user

    def _serialize(self, user: User, attr, data, **kwargs) -> int:
        return user.id
