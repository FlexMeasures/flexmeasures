from typing import Any

from flexmeasures.data import ma
from marshmallow import Schema, fields, validates, post_load
from flask_security import current_user

from flexmeasures.data import db
from flexmeasures.data.models.user import Account, AccountRole
from flexmeasures.data.schemas.attributes import JSON
from flexmeasures.data.schemas.utils import (
    FMValidationError,
    MarshmallowClickMixin,
    with_appcontext_if_needed,
)
from flexmeasures.utils.validation_utils import validate_color_hex, validate_url
from flexmeasures.auth.policy import (
    user_has_admin_access,
    ACCOUNT_ADMIN_ROLE,
    CONSULTANT_ROLE,
    CONSULTANCY_ACCOUNT_ROLE,
)


class AccountRoleSchema(ma.SQLAlchemySchema):
    """AccountRole schema, with validations."""

    class Meta:
        model = AccountRole

    id = ma.auto_field(dump_only=True)
    name = ma.auto_field()
    accounts = fields.Nested("AccountSchema", exclude=("account_roles",), many=True)


class AccountSchema(ma.SQLAlchemySchema):
    """Account schema, with validations."""

    class Meta:
        model = Account

    id = ma.auto_field(dump_only=True)
    name = ma.auto_field(required=True)
    primary_color = ma.auto_field(required=False)
    secondary_color = ma.auto_field(required=False)
    logo_url = ma.auto_field(required=False)
    attributes = JSON(required=False, load_default={})
    account_roles = fields.Nested("AccountRoleSchema", exclude=("accounts",), many=True)
    consultancy_account_id = ma.auto_field()

    @validates("primary_color")
    def validate_primary_color(self, value, **kwargs):
        try:
            validate_color_hex(value)
        except ValueError as e:
            raise FMValidationError(str(e))

    @validates("secondary_color")
    def validate_secondary_color(self, value, **kwargs):
        try:
            validate_color_hex(value)
        except ValueError as e:
            raise FMValidationError(str(e))

    @validates("logo_url")
    def validate_logo_url(self, value, **kwargs):
        try:
            validate_url(value)
        except ValueError as e:
            raise FMValidationError(str(e))


class AccountCreateSchema(Schema):
    """Schema for creating an account via API."""

    name = fields.String(required=True)
    consultancy_account_id = fields.Integer(required=False, allow_none=True)

    @validates("name")
    def validate_name(self, value, **kwargs):
        if not value.strip():
            raise FMValidationError("Account name cannot be empty.")

        # check if account with this name already exists
        existing_account = db.session.execute(
            db.select(Account).filter_by(name=value)
        ).scalar_one_or_none()
        if existing_account:
            raise FMValidationError(f"An account with name '{value}' already exists.")

    @validates("consultancy_account_id")
    @with_appcontext_if_needed()
    def validate_consultancy_account_id(self, value, **kwargs):
        """Validate consultancy_account_id field.

        Rules:
        - Must be an existing account (if provided)
        - Admins can set it to any account
        - Non-admins can only set it to their own account if:
          - Their account has the consultancy account role AND
          - They have the consultant or account-admin user role
        """
        # Admins can set any consultancy account (including None)
        if user_has_admin_access(current_user, "update"):
            return

        # For non-admins, whether value is provided or None, they need the right roles
        # because None will be defaulted to their account in the API

        # Check that the user's account has the consultancy account role
        if not current_user.account.has_role(CONSULTANCY_ACCOUNT_ROLE):
            raise FMValidationError(
                f"Your account must have the '{CONSULTANCY_ACCOUNT_ROLE}' role "
                "to be set as a consultancy account."
            )

        # Check that the user has consultant or account-admin role
        if not (
            current_user.has_role(CONSULTANT_ROLE)
            or current_user.has_role(ACCOUNT_ADMIN_ROLE)
        ):
            raise FMValidationError(
                f"You must have the '{CONSULTANT_ROLE}' or '{ACCOUNT_ADMIN_ROLE}' "
                "role to set a consultancy account."
            )

        # If value is None, validation passes
        if value is None:
            return

        # From here on, we're validating a non-None value that was explicitly provided

        # Check that the account exists
        consultancy_account = db.session.get(Account, value)
        if consultancy_account is None:
            raise FMValidationError(f"No account found with id {value}.")

        # Non-admins can only set it to their own account
        if value != current_user.account.id:
            raise FMValidationError(
                "You can only set consultancy_account_id to your own account."
            )

    @post_load
    @with_appcontext_if_needed()
    def set_consultancy_account_default(self, data, **kwargs):
        """Set consultancy_account_id to current user's account for consultants/account-admins.

        This runs after validation, so we know the user has the required roles.
        Only applies when consultancy_account_id is None or missing.
        """
        if (
            "consultancy_account_id" not in data
            or data["consultancy_account_id"] is None
        ):
            # Admins don't get auto-defaulting
            if user_has_admin_access(current_user, "update"):
                return data

            # For consultants/account-admins, default to their account
            # (validation already confirmed they have the required roles)
            if current_user.has_role(CONSULTANT_ROLE) or current_user.has_role(
                ACCOUNT_ADMIN_ROLE
            ):
                data["consultancy_account_id"] = current_user.account.id

        return data


class AccountPatchSchema(Schema):
    """Schema for updating an account via API."""

    name = fields.String(required=False)
    primary_color = fields.String(required=False, allow_none=True)
    secondary_color = fields.String(required=False, allow_none=True)
    logo_url = fields.String(required=False, allow_none=True)
    consultancy_account_id = fields.Integer(required=False, allow_none=True)
    attributes = JSON(required=False)
    account_roles = fields.List(fields.Integer(), required=False)

    @validates("primary_color")
    def validate_primary_color(self, value, **kwargs):
        try:
            validate_color_hex(value)
        except ValueError as e:
            raise FMValidationError(str(e))

    @validates("secondary_color")
    def validate_secondary_color(self, value, **kwargs):
        try:
            validate_color_hex(value)
        except ValueError as e:
            raise FMValidationError(str(e))

    @validates("logo_url")
    def validate_logo_url(self, value, **kwargs):
        try:
            validate_url(value)
        except ValueError as e:
            raise FMValidationError(str(e))

    @validates("consultancy_account_id")
    @with_appcontext_if_needed()
    def validate_consultancy_account_id(self, value, **kwargs):
        """Validate consultancy_account_id field.

        Rules:
        - Must be an existing account (if provided)
        - Admins can set it to any account or clear it
        - Non-admins can set it to their own account or clear it if:
          - Their account has the consultancy account role AND
          - They have the consultant or account-admin user role
        """
        # Admins can set any consultancy account or clear it (set to None)
        if user_has_admin_access(current_user, "update"):
            return

        # For non-admins, check roles whether setting or clearing
        # They need proper roles to modify this field at all

        # Check that the user's account has the consultancy account role
        if not current_user.account.has_role(CONSULTANCY_ACCOUNT_ROLE):
            raise FMValidationError(
                f"Your account must have the '{CONSULTANCY_ACCOUNT_ROLE}' role "
                "to be set as a consultancy account."
            )

        # Check that the user has consultant or account-admin role
        if not (
            current_user.has_role(CONSULTANT_ROLE)
            or current_user.has_role(ACCOUNT_ADMIN_ROLE)
        ):
            raise FMValidationError(
                f"You must have the '{CONSULTANT_ROLE}' or '{ACCOUNT_ADMIN_ROLE}' "
                "role to set a consultancy account."
            )

        # If clearing the relationship (None), validation passes after role checks
        if value is None:
            return

        # From here on, we're setting a non-None value

        # Check that the account exists
        consultancy_account = db.session.get(Account, value)
        if consultancy_account is None:
            raise FMValidationError(f"No account found with id {value}.")

        # Non-admins can only set it to their own account
        if value != current_user.account.id:
            raise FMValidationError(
                "You can only set consultancy_account_id to your own account."
            )


class AccountIdField(MarshmallowClickMixin, fields.Int):
    """Field that deserializes to an Account and serializes back to an integer."""

    @with_appcontext_if_needed()
    def _deserialize(self, value: Any, attr, data, **kwargs) -> Account:
        """Turn an account id into an Account."""
        account_id: int = super()._deserialize(value, attr, data, **kwargs)
        account = db.session.get(Account, account_id)
        if account is None:
            raise FMValidationError(f"No account found with id {account_id}.")
        # lazy loading now (account somehow is not in the session after this)
        account.account_roles
        return account

    def _serialize(self, value: Account, attr, obj, **kwargs):
        """Turn an Account into a source id."""
        return value.id


class AccountIdOrListField(fields.Field):
    """Field that accepts a single account ID or a non-empty list of account IDs.

    Both ``42`` and ``[42, 99]`` are accepted.  Always deserializes to a list of
    :class:`~flexmeasures.data.models.user.Account` instances.

    The field is intentionally expressed as a union of ``integer`` and
    ``array[integer]`` rather than always requiring a list, so that future
    OpenAPI generation can emit a ``oneOf`` schema for it.
    """

    def _deserialize(self, value: Any, attr, data, **kwargs) -> list[Account]:
        _item_field = AccountIdField()
        if isinstance(value, list):
            if len(value) == 0:
                raise FMValidationError("Must be a non-empty list of account IDs.")
            return [_item_field._deserialize(v, attr, data, **kwargs) for v in value]
        return [_item_field._deserialize(value, attr, data, **kwargs)]

    def _serialize(self, value: Any, attr, obj, **kwargs):
        if value is None:
            return None
        if isinstance(value, list):
            return [a.id if hasattr(a, "id") else a for a in value]
        return value.id if hasattr(value, "id") else value
