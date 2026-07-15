from typing import Any

from flexmeasures.data import ma
from marshmallow import Schema, fields, validates, post_load
from flask_security import current_user
from werkzeug.exceptions import Forbidden

from flexmeasures.data import db
from flexmeasures.data.models.user import Account, AccountRole, Plan
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
    plan_id = ma.auto_field(allow_none=True)

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


def _validate_consultancy_account_id_permissions(value, allow_clearing: bool = False):
    """Shared validation logic for consultancy_account_id field.

    Args:
        value: The consultancy_account_id value to validate (can be None)
        allow_clearing: If True, allows None value after role checks (for PATCH)
                       If False, None is allowed without additional validation (for POST with defaulting)

    Raises:
        Forbidden: When user lacks required permissions
        FMValidationError: When account doesn't exist or other validation fails

    Rules:
        - Admins can set/clear any consultancy_account_id
        - Non-admins need both:
          - Account role: Consultancy
          - User role: consultant OR account-admin
        - Non-admins can only set it to their own account
    """
    # Admins can do anything
    if user_has_admin_access(current_user, "update"):
        return

    # For non-admins, check required roles first (before allowing None or validating value)
    if not current_user.account.has_role(CONSULTANCY_ACCOUNT_ROLE):
        raise Forbidden(
            f"Your account must have the '{CONSULTANCY_ACCOUNT_ROLE}' role "
            "to be set as a consultancy account."
        )

    if not (
        current_user.has_role(CONSULTANT_ROLE)
        or current_user.has_role(ACCOUNT_ADMIN_ROLE)
    ):
        raise Forbidden(
            f"You must have the '{CONSULTANT_ROLE}' or '{ACCOUNT_ADMIN_ROLE}' "
            "role to set a consultancy account."
        )

    # After role checks, None is allowed
    if value is None:
        return

    # Validate the explicit value provided
    consultancy_account = db.session.get(Account, value)
    if consultancy_account is None:
        raise FMValidationError(f"No account found with id {value}.")

    # Non-admins can only set their own account
    if value != current_user.account.id:
        raise Forbidden("You can only set consultancy_account_id to your own account.")


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
        """Validate consultancy_account_id field for account creation.

        Uses shared validation logic. For POST requests, None is allowed
        and will be defaulted in @post_load.
        """
        _validate_consultancy_account_id_permissions(value, allow_clearing=False)

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
    plan_id = fields.Integer(required=False, allow_none=True)
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
        """Validate consultancy_account_id field for account updates.

        Uses shared validation logic. For PATCH requests, None clears the relationship.
        """
        _validate_consultancy_account_id_permissions(value, allow_clearing=True)

    @validates("plan_id")
    @with_appcontext_if_needed()
    def validate_plan_id(self, value, **kwargs):
        """Validate the plan an account is being put on.

        Which plan an account is on decides what it may ask of the server, so only admins
        get to say. None clears the plan, which falls the account back on the server config.
        """
        if not user_has_admin_access(current_user, "update"):
            raise Forbidden("You must be an admin to put an account on a plan.")
        if value is None:
            return
        plan = db.session.get(Plan, value)
        if plan is None:
            raise FMValidationError(f"No plan found with id {value}.")
        if plan.legacy:
            # A legacy plan keeps applying to the accounts already on it, but is not handed out anymore
            raise FMValidationError(f"Plan '{plan.name}' is a legacy plan.")

    @post_load
    @with_appcontext_if_needed()
    def transform_account_roles(self, data, **kwargs):
        """Transform account_roles from list of IDs to list of AccountRole objects.

        Validates that:
        - account_roles is a list of integers
        - All role IDs exist in the database

        Raises:
            FMValidationError: If validation fails
        """
        if "account_roles" not in data:
            return data

        raw_roles = data["account_roles"]

        # Validate it's a list of integers
        if not isinstance(raw_roles, list) or any(
            not isinstance(role_id, int) for role_id in raw_roles
        ):
            raise FMValidationError("account_roles must be a list of integer IDs.")

        # Resolve IDs to AccountRole objects
        resolved_roles = [db.session.get(AccountRole, role_id) for role_id in raw_roles]

        # Check for invalid IDs
        invalid_role_ids = [
            role_id
            for role_id, db_role in zip(raw_roles, resolved_roles)
            if db_role is None
        ]
        if invalid_role_ids:
            raise FMValidationError(f"Invalid account role ID(s): {invalid_role_ids}.")

        # Replace list of IDs with list of AccountRole objects
        data["account_roles"] = resolved_roles
        return data


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
