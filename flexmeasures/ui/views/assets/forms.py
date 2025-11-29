from __future__ import annotations

import copy
import json

from flask import current_app
from flask_security import current_user
from flask_wtf import FlaskForm
from sqlalchemy import select
from wtforms import StringField, DecimalField, SelectField, IntegerField
from wtforms.validators import DataRequired, optional
from marshmallow import ValidationError

from flexmeasures.auth.policy import user_has_admin_access
from flexmeasures.data import db
from flexmeasures.data.models.generic_assets import GenericAssetType
from flexmeasures.data.models.user import Account
from flexmeasures.data.schemas.generic_assets import SensorsToShowAsKPIsSchema


class AssetForm(FlaskForm):
    """The default asset form only allows to edit the name and location."""

    name = StringField(
        "Name",
        validators=[DataRequired()],
    )
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
    sensors_to_show_as_kpis = StringField(
        "Sensors to show as KPIs (JSON)",
        default="[]",
    )

    def validate_on_submit(self):
        if (
            hasattr(self, "generic_asset_type_id")
            and self.generic_asset_type_id.data == -1
        ):
            self.generic_asset_type_id.data = (
                ""  # cannot be coerced to int so will be flagged as invalid input
            )

        result = super().validate_on_submit()
        return result

    # Custom validator using Marshmallow
    def validate_sensors_to_show_as_kpis(self, field):
        try:
            # First, try to parse the input as JSON
            value = json.loads(field.data)
        except json.JSONDecodeError:
            field.errors.append("Invalid JSON string.")
            return

        # Now, use Marshmallow schema to validate the structure of the data
        schema = SensorsToShowAsKPIsSchema()
        try:
            # Validate the parsed JSON data using the schema
            schema.load({"sensors_to_show_as_kpis": value})
        except ValidationError as e:
            field.errors.append(str(e))
            return

    def to_json(self) -> dict:
        """turn form data into a JSON object"""
        data = copy.copy(self.data)
        if data.get("longitude") is not None:
            data["longitude"] = float(data["longitude"])
        if data.get("latitude") is not None:
            data["latitude"] = float(data["latitude"])
        if data.get("parent_asset_id") is not None:
            data["parent_asset_id"] = int(data["parent_asset_id"])
        if "csrf_token" in data:
            del data["csrf_token"]

        return data

    def with_options(self):
        if "generic_asset_type_id" in self:
            self.generic_asset_type_id.choices = [(-1, "--Select type--")] + [
                (atype.id, atype.name)
                for atype in db.session.scalars(select(GenericAssetType)).all()
            ]
        if "account_id" in self:
            selectable_accounts = [current_user.account]
            if current_user.has_role("consultant"):
                selectable_accounts += current_user.account.consultancy_client_accounts
            if user_has_admin_access(current_user, "create_children"):
                selectable_accounts = db.session.scalars(select(Account)).all()
            self.account_id.choices = [(-1, "--Select account--")] + [
                (account.id, account.name) for account in selectable_accounts
            ]


class NewAssetForm(AssetForm):
    """Here, in addition, we allow to set asset type and account."""

    generic_asset_type_id = SelectField(
        "Asset type", coerce=int, validators=[DataRequired()]
    )
    account_id = SelectField("Account", coerce=int, validators=[optional()])
    parent_asset_id = IntegerField("Parent Asset Id", validators=[optional()])

    def set_account(self) -> tuple[Account | None, str | None]:
        """Set an account for the to-be-created asset.
        Return the account (if available) and an error message"""

        account_error = None

        if self.account_id.data == -1 or self.account_id.data is None:
            if user_has_admin_access(current_user, "update"):
                return None, None  # Account can be None (public asset)
            else:
                return None, "Please pick an existing account."

        account = db.session.execute(
            select(Account).filter_by(id=int(self.account_id.data))
        ).scalar_one_or_none()

        if account:
            self.account_id.data = account.id
        else:
            account_error = f"Account {self.account_id.data} could not be found."
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
