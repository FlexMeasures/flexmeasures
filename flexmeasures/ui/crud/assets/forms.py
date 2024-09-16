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
    SelectMultipleField,
    ValidationError,
)
from wtforms.validators import DataRequired, optional
from typing import Optional

from flexmeasures.auth.policy import user_has_admin_access
from flexmeasures.data import db
from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.models.user import Account
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.ui.crud.assets.utils import (
    get_allowed_price_sensor_data,
    get_allowed_inflexible_sensor_data,
)


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
    production_price_sensor_id = SelectField(
        "Production price sensor", coerce=int, validate_choice=False
    )
    consumption_price_sensor_id = SelectField(
        "Consumption price sensor", coerce=int, validate_choice=False
    )
    inflexible_device_sensor_ids = SelectMultipleField(
        "Inflexible device sensors", coerce=int, validate_choice=False
    )

    def validate_inflexible_device_sensor_ids(form, field):
        if field.data and len(field.data) > 1 and -1 in field.data:
            raise ValidationError(
                "No sensor choice is not allowed together with sensor ids."
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
        if (
            hasattr(self, "production_price_sensor_id")
            and self.production_price_sensor_id is not None
            and self.production_price_sensor_id.data == -1
        ):
            self.production_price_sensor_id.data = None
        if (
            hasattr(self, "consumption_price_sensor_id")
            and self.consumption_price_sensor_id is not None
            and self.consumption_price_sensor_id.data == -1
        ):
            self.consumption_price_sensor_id.data = None
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

    def with_price_sensors(
        self, asset: GenericAsset, account_id: Optional[int]
    ) -> None:
        allowed_price_sensor_data = get_allowed_price_sensor_data(account_id)
        for sensor_name in ("production_price", "consumption_price"):
            sensor_id = getattr(asset, sensor_name + "_sensor_id") if asset else None
            if sensor_id:
                sensor = Sensor.query.get(sensor_id)
                allowed_price_sensor_data[sensor_id] = f"{asset.name}:{sensor.name}"
            choices = [(id, label) for id, label in allowed_price_sensor_data.items()]
            choices = [(-1, "--Select sensor id--")] + choices
            form_sensor = getattr(self, sensor_name + "_sensor_id")
            form_sensor.choices = choices
            if sensor_id is None:
                form_sensor.default = (-1, "--Select sensor id--")
            else:
                form_sensor.default = (sensor_id, allowed_price_sensor_data[sensor_id])
            setattr(self, sensor_name + "_sensor_id", form_sensor)

    def with_inflexible_sensors(
        self, asset: GenericAsset, account_id: Optional[int]
    ) -> None:
        allowed_inflexible_sensor_data = get_allowed_inflexible_sensor_data(account_id)
        linked_sensor_data = {}
        if asset:
            linked_sensors = asset.get_inflexible_device_sensors()
            linked_sensor_data = {
                sensor.id: f"{asset.name}:{sensor.name}" for sensor in linked_sensors
            }

        all_sensor_data = {**allowed_inflexible_sensor_data, **linked_sensor_data}
        choices = [(id, label) for id, label in all_sensor_data.items()]
        choices = [(-1, "--Select sensor id--")] + choices
        self.inflexible_device_sensor_ids.choices = choices

        default = [-1]
        if linked_sensor_data:
            default = [id for id in linked_sensor_data]
        self.inflexible_device_sensor_ids.default = default

    def with_sensors(
        self,
        asset: GenericAsset,
        account_id: Optional[int],
    ) -> None:
        if current_app.config.get("FLEXMEASURES_HIDE_FLEXCONTEXT_EDIT", False):
            del self.inflexible_device_sensor_ids
            del self.production_price_sensor_id
            del self.consumption_price_sensor_id
        else:
            self.with_price_sensors(asset, account_id)
            self.with_inflexible_sensors(asset, account_id)


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
