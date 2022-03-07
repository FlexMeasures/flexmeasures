from flask.cli import with_appcontext
from marshmallow import fields

from flexmeasures.data.models.user import Account
from flexmeasures.data.schemas.utils import FMValidationError, MarshmallowClickMixin


class AccountIdField(fields.Int, MarshmallowClickMixin):
    """Field that de-serializes to a Sensor and serializes back to an integer."""

    @with_appcontext
    def _deserialize(self, value, attr, obj, **kwargs) -> Account:
        """Turn a source id into a DataSource."""
        account = Account.query.get(value)
        account.account_roles  # lazy loading now
        if account is None:
            raise FMValidationError(f"No account found with id {value}.")
        return account

    def _serialize(self, account, attr, data, **kwargs):
        """Turn a DataSource into a source id."""
        return account.id
