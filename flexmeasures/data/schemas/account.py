from flask.cli import with_appcontext
from flexmeasures.data import ma
from marshmallow import fields, validates

from flexmeasures.data import db
from flexmeasures.data.models.user import (
    Account as AccountModel,
    AccountRole as AccountRoleModel,
)
from flexmeasures.data.schemas.utils import FMValidationError, MarshmallowClickMixin
from flexmeasures.utils.validation_utils import validate_color_hex, validate_url


class AccountRoleSchema(ma.SQLAlchemySchema):
    """AccountRole schema, with validations."""

    class Meta:
        model = AccountRoleModel

    id = ma.auto_field(dump_only=True)
    name = ma.auto_field()
    accounts = fields.Nested("AccountSchema", exclude=("account_roles",), many=True)


class AccountSchema(ma.SQLAlchemySchema):
    """Account schema, with validations."""

    class Meta:
        model = AccountModel

    id = ma.auto_field(dump_only=True)
    name = ma.auto_field(required=True)
    primary_color = ma.auto_field(required=False)
    secondary_color = ma.auto_field(required=False)
    logo_url = ma.auto_field(required=False)
    account_roles = fields.Nested("AccountRoleSchema", exclude=("accounts",), many=True)
    consultancy_account_id = ma.auto_field()

    @validates("primary_color")
    def validate_primary_color(self, value):
        try:
            validate_color_hex(value)
        except ValueError as e:
            raise FMValidationError(str(e))

    @validates("secondary_color")
    def validate_secondary_color(self, value):
        try:
            validate_color_hex(value)
        except ValueError as e:
            raise FMValidationError(str(e))

    @validates("logo_url")
    def validate_logo_url(self, value):
        try:
            validate_url(value)
        except ValueError as e:
            raise FMValidationError(str(e))


class AccountIdField(fields.Int, MarshmallowClickMixin):
    """Field that deserializes to an Account and serializes back to an integer."""

    @with_appcontext
    def _deserialize(self, value, attr, obj, **kwargs) -> AccountModel:
        """Turn an account id into an Account."""
        account = db.session.get(AccountModel, value)
        if account is None:
            raise FMValidationError(f"No account found with id {value}.")
        # lazy loading now (account somehow is not in the session after this)
        account.account_roles
        return account

    def _serialize(self, account, attr, data, **kwargs):
        """Turn an Account into a source id."""
        return account.id
