import copy

from flask_wtf import FlaskForm
from sqlalchemy import select
from sqlalchemy.sql.expression import or_
from wtforms import (
    StringField,
    DecimalField,
    SelectField,
    SelectMultipleField,
    ValidationError,
)
from wtforms.validators import DataRequired, optional
from typing import Optional

from flexmeasures.data import db
from flexmeasures.data.models.generic_assets import (
    GenericAsset,
    GenericAssetType,
    GenericAssetInflexibleSensorRelationship,
)
from flexmeasures.data.models.user import Account
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.utils.unit_utils import is_energy_price_unit, is_energy_unit


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

    def get_allowed_price_sensor_data(
        self, account_id: Optional[int]
    ) -> dict[int, str]:
        """
        Return a list of sensors which the user can add
        as consumption_price_sensor_id or production_price_sensor_id.
        For each sensor we get data as sensor_id: asset_name:sensor_name.
        """
        if not account_id:
            assets = db.session.scalars(
                select(GenericAsset).filter(GenericAsset.account_id.is_(None))
            ).all()
        else:
            assets = db.session.scalars(
                select(GenericAsset).filter(
                    or_(
                        GenericAsset.account_id == account_id,
                        GenericAsset.account_id.is_(None),
                    )
                )
            ).all()

        sensors_data = list()
        for asset in assets:
            sensors_data += [
                (sensor.id, asset.name, sensor.name, sensor.unit)
                for sensor in asset.sensors
            ]

        return {
            sensor_id: f"{asset_name}:{sensor_name}"
            for sensor_id, asset_name, sensor_name, sensor_unit in sensors_data
            if is_energy_price_unit(sensor_unit)
        }

    def get_allowed_inflexible_sensor_data(
        self, account_id: Optional[int]
    ) -> dict[int, str]:
        """
        Return a list of sensors which the user can add
        as inflexible device sensors.
        For each sensor we get data as sensor_id: asset_name:sensor_name.
        """
        query = None
        if not account_id:
            query = select(GenericAsset).filter(GenericAsset.account_id.is_(None))
        else:
            query = select(GenericAsset).filter(GenericAsset.account_id == account_id)
        assets = db.session.scalars(query).all()

        sensors_data = list()
        for asset in assets:
            sensors_data += [
                (sensor.id, asset.name, sensor.name, sensor.unit)
                for sensor in asset.sensors
            ]

        return {
            sensor_id: f"{asset_name}:{sensor_name}"
            for sensor_id, asset_name, sensor_name, sensor_unit in sensors_data
            if is_energy_unit(sensor_unit)
        }

    def with_price_senors(self, asset: GenericAsset, account_id: Optional[int]) -> None:
        allowed_price_sensor_data = self.get_allowed_price_sensor_data(account_id)
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
        allowed_inflexible_sensor_data = self.get_allowed_inflexible_sensor_data(
            account_id
        )
        linked_sensor_data = {}
        if asset:
            linked_sensors = (
                db.session.query(
                    GenericAssetInflexibleSensorRelationship.inflexible_sensor_id,
                    Sensor.name,
                )
                .join(
                    Sensor,
                    GenericAssetInflexibleSensorRelationship.inflexible_sensor_id
                    == Sensor.id,
                )
                .filter(
                    GenericAssetInflexibleSensorRelationship.generic_asset_id
                    == asset.id
                )
                .all()
            )
            linked_sensor_data = {
                sensor_id: f"{asset.name}:{sensor_name}"
                for sensor_id, sensor_name in linked_sensors
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
        self.with_price_senors(asset, account_id)
        self.with_inflexible_sensors(asset, account_id)


class NewAssetForm(AssetForm):
    """Here, in addition, we allow to set asset type and account."""

    generic_asset_type_id = SelectField(
        "Asset type", coerce=int, validators=[DataRequired()]
    )
    account_id = SelectField("Account", coerce=int)
