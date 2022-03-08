from flask.cli import with_appcontext
from marshmallow import fields

from flexmeasures.data.models.user import Account
from flexmeasures.data.schemas.utils import FMValidationError, MarshmallowClickMixin


class AccountIdField(fields.Int, MarshmallowClickMixin):
    """Field that deserializes to an Account and serializes back to an integer."""

    @with_appcontext
    def _deserialize(self, value, attr, obj, **kwargs) -> Account:
        """Turn an account id into an Account."""
        account = Account.query.get(value)
        if account is None:
            raise FMValidationError(f"No account found with id {value}.")
        # lazy loading now (account somehow is not in the session after this)
        account.account_roles
        return account

    def _serialize(self, account, attr, data, **kwargs):
        """Turn an Account into a source id."""
        return account.id
