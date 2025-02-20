from __future__ import annotations

import copy

from flask import current_app
from flask_security import current_user
from flask_wtf import FlaskForm
from sqlalchemy import select
from wtforms import (
    StringField,
    DecimalField,
    SelectField,
)
from wtforms.validators import DataRequired, optional

from flexmeasures.auth.policy import user_has_admin_access
from flexmeasures.data import db
from flexmeasures.data.models.generic_assets import GenericAssetType
from flexmeasures.data.models.user import Account


class AssetForm(FlaskForm):
    """The default asset form only allows to edit the name and location."""

    name = StringField("Name")
    latitude = DecimalField(
        "Latitude",
        validators=[optional()],
        places=None,
        render_kw={"placeholder": "--Click the map or enter a latitude--"},
    )
    longitude = DecimalField(
        "Longitude",
        validators=[optional()],
        places=None,
        render_kw={"placeholder": "--Click the map or enter a longitude--"},
    )
    attributes = StringField("Other attributes (JSON)", default="{}")
    flex_context = StringField(
        "Flex context",
        default="{}",
        description=(
            "This field accepts a JSON string to define the flex-context."
            " These are defaults that, if needed, users can temporarily override when calling for a schedule via the API, by setting different flex-context fields in the API request."
        ),
    )

    def validate_on_submit(self):
        if (
            hasattr(self, "generic_asset_type_id")
            and self.generic_asset_type_id.data == -1
        ):
            self.generic_asset_type_id.data = (
                ""  # cannot be coerced to int so will be flagged as invalid input
            )
        if hasattr(self, "account_id") and self.account_id.data == -1:
            del self.account_id  # asset will be public
        result = super().validate_on_submit()
        return result

    def to_json(self) -> dict:
        """turn form data into a JSON we can POST to our internal API"""
        data = copy.copy(self.data)
        if data.get("longitude") is not None:
            data["longitude"] = float(data["longitude"])
        if data.get("latitude") is not None:
            data["latitude"] = float(data["latitude"])

        if "csrf_token" in data:
            del data["csrf_token"]

        return data

    def process_api_validation_errors(self, api_response: dict):
        """Process form errors from the API for the WTForm"""
        if not isinstance(api_response, dict):
            return
        for error_header in ("json", "validation_errors"):
            if error_header not in api_response:
                continue
            for field in list(self._fields.keys()):
                if field in list(api_response[error_header].keys()):
                    field_errors = api_response[error_header][field]
                    if isinstance(field_errors, list):
                        self._fields[field].errors += api_response[error_header][field]
                    else:
                        self._fields[field].errors.append(
                            api_response[error_header][field]
                        )

    def with_options(self):
        if "generic_asset_type_id" in self:
            self.generic_asset_type_id.choices = [(-1, "--Select type--")] + [
                (atype.id, atype.name)
                for atype in db.session.scalars(select(GenericAssetType)).all()
            ]
        if "account_id" in self:
            self.account_id.choices = [(-1, "--Select account--")] + [
                (account.id, account.name)
                for account in db.session.scalars(select(Account)).all()
            ]


class NewAssetForm(AssetForm):
    """Here, in addition, we allow to set asset type and account."""

    generic_asset_type_id = SelectField(
        "Asset type", coerce=int, validators=[DataRequired()]
    )
    account_id = SelectField("Account", coerce=int)

    def set_account(self) -> tuple[Account | None, str | None]:
        """Set an account for the to-be-created asset.
        Return the account (if available) and an error message"""
        account_error = None

        if self.account_id.data == -1:
            if user_has_admin_access(current_user, "update"):
                return None, None  # Account can be None (public asset)
            else:
                account_error = "Please pick an existing account."

        account = db.session.execute(
            select(Account).filter_by(id=int(self.account_id.data))
        ).scalar_one_or_none()

        if account:
            self.account_id.data = account.id
        else:
            current_app.logger.error(account_error)
        return account, account_error

    def set_asset_type(self) -> tuple[GenericAssetType | None, str | None]:
        """Set an asset type for the to-be-created asset.
        Return the asset type (if available) and an error message."""
        asset_type = None
        asset_type_error = None

        if int(self.generic_asset_type_id.data) == -1:
            asset_type_error = "Pick an existing asset type."
        else:
            asset_type = db.session.execute(
                select(GenericAssetType).filter_by(
                    id=int(self.generic_asset_type_id.data)
                )
            ).scalar_one_or_none()

        if asset_type:
            self.generic_asset_type_id.data = asset_type.id
        else:
            current_app.logger.error(asset_type_error)
        return asset_type, asset_type_error
