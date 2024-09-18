from __future__ import annotations

import json

from marshmallow import validates, ValidationError, fields, validates_schema
from flask_security import current_user
from sqlalchemy import select

from flexmeasures.data import ma, db
from flexmeasures.data.models.user import Account
from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.schemas.locations import LatitudeField, LongitudeField
from flexmeasures.data.schemas.utils import (
    FMValidationError,
    MarshmallowClickMixin,
    with_appcontext_if_needed,
)
from flexmeasures.auth.policy import user_has_admin_access
from flexmeasures.cli import is_running as running_as_cli


class JSON(fields.Field):
    def _deserialize(self, value, attr, data, **kwargs) -> dict:
        try:
            return json.loads(value)
        except ValueError:
            raise ValidationError("Not a valid JSON string.")

    def _serialize(self, value, attr, data, **kwargs) -> str:
        return json.dumps(value)


class SensorsToShowSchema(fields.Field):
    """
    Schema for validating and deserializing the `sensors_to_show` attribute of a GenericAsset.

    The `sensors_to_show` attribute defines which sensors should be displayed for a particular asset.
    It supports various input formats, which are standardized into a list of dictionaries, each containing
    a `title` (optional) and a `sensors` list. The valid input formats include:

    - A single sensor ID (int): `42` -> `{"title": None, "sensors": [42]}`
    - A list of sensor IDs (list of ints): `[42, 43]` -> `{"title": None, "sensors": [42, 43]}`
    - A dictionary with a title and sensor: `{"title": "Temperature", "sensor": 42}` -> `{"title": "Temperature", "sensors": [42]}`
    - A dictionary with a title and sensors: `{"title": "Pressure", "sensors": [42, 43]}`

    Validation ensures that:
    - The input is either a list, integer, or dictionary.
    - If the input is a dictionary, it must contain either `sensor` (int) or `sensors` (list of ints).
    - All sensor IDs must be valid integers.

    Example Input:
    - `[{"title": "Test", "sensors": [1, 2]}, {"title": None, "sensors": [3, 4]}, 5]`

    Example Output (Standardized):
    - `[{"title": "Test", "sensors": [1, 2]}, {"title": None, "sensors": [3, 4]}, {"title": None, "sensors": [5]}]`
    """

    def deserialize(self, value, **kwargs) -> list:
        """
        Validate and deserialize the input value.
        """
        try:
            # Parse JSON if input is a string
            if isinstance(value, str):
                value = json.loads(value)

            # Ensure value is a list
            if not isinstance(value, list):
                raise ValidationError("sensors_to_show should be a list.")

            # Standardize each item in the list
            return [self._standardize_item(item) for item in value]
        except json.JSONDecodeError:
            raise ValidationError("Invalid JSON string.")

    def _standardize_item(self, item) -> dict:
        """
        Standardize different input formats to a consistent dictionary format.
        """
        if isinstance(item, int):
            return {"title": None, "sensors": [item]}
        elif isinstance(item, list):
            if not all(isinstance(sensor_id, int) for sensor_id in item):
                raise ValidationError(
                    "All elements in a list within 'sensors_to_show' must be integers."
                )
            return {"title": None, "sensors": item}
        elif isinstance(item, dict):
            if "title" not in item:
                raise ValidationError("Dictionary must contain a 'title' key.")
            else:
                title = item["title"]
                if not isinstance(title, str) and title is not None:
                    raise ValidationError("'title' value must be a string.")

            if "sensor" in item:
                sensor = item["sensor"]
                if not isinstance(sensor, int):
                    raise ValidationError("'sensor' value must be an integer.")
                return {"title": title, "sensors": [sensor]}
            elif "sensors" in item:
                sensors = item["sensors"]
                if not isinstance(sensors, list) or not all(
                    isinstance(sensor_id, int) for sensor_id in sensors
                ):
                    raise ValidationError("'sensors' value must be a list of integers.")
                return {"title": title, "sensors": sensors}
            else:
                raise ValidationError(
                    "Dictionary must contain either 'sensor' or 'sensors' key."
                )
        else:
            raise ValidationError(
                "Invalid item type in 'sensors_to_show'. Expected int, list, or dict."
            )

    @classmethod
    def flatten(cls, nested_list) -> list[int]:
        """
        Flatten a nested list of sensors or sensor dictionaries into a unique list of sensor IDs.

        This method processes the following formats, for each of the entries of the nested list:
        - A list of sensor IDs: `[1, 2, 3]`
        - A list of dictionaries where each dictionary contains a `sensors` list or a `sensor` key:
        `[{"title": "Temperature", "sensors": [1, 2]}, {"title": "Pressure", "sensor": 3}]`
        - Mixed formats: `[{"title": "Temperature", "sensors": [1, 2]}, {"title": "Pressure", "sensor": 3}, 4, 5, 1]`

        It extracts all sensor IDs, removes duplicates, and returns a flattened list of unique sensor IDs.

        Args:
            nested_list (list): A list containing sensor IDs, or dictionaries with `sensors` or `sensor` keys.

        Returns:
            list: A unique list of sensor IDs.
        """

        all_objects = []
        for s in nested_list:
            if isinstance(s, list):
                all_objects.extend(s)
            elif isinstance(s, dict):
                if "sensors" in s:
                    all_objects.extend(s["sensors"])
                if "sensor" in s:
                    all_objects.append(s["sensor"])
            else:
                all_objects.append(s)
        return list(dict.fromkeys(all_objects).keys())


class GenericAssetSchema(ma.SQLAlchemySchema):
    """
    GenericAsset schema, with validations.
    """

    id = ma.auto_field(dump_only=True)
    name = fields.Str(required=True)
    account_id = ma.auto_field()
    owner = ma.Nested("AccountSchema", dump_only=True, only=("id", "name"))
    latitude = LatitudeField(allow_none=True)
    longitude = LongitudeField(allow_none=True)
    generic_asset_type_id = fields.Integer(required=True)
    generic_asset_type = ma.Nested(
        "GenericAssetTypeSchema", dump_only=True, only=("id", "name")
    )
    attributes = JSON(required=False)
    parent_asset_id = fields.Int(required=False, allow_none=True)
    child_assets = ma.Nested(
        "GenericAssetSchema",
        many=True,
        dump_only=True,
        only=("id", "name", "account_id", "generic_asset_type"),
    )
    sensors = ma.Nested("SensorSchema", many=True, dump_only=True, only=("id", "name"))
    production_price_sensor_id = fields.Int(required=False, allow_none=True)
    consumption_price_sensor_id = fields.Int(required=False, allow_none=True)
    inflexible_device_sensor_ids = fields.List(
        fields.Int, required=False, allow_none=True
    )

    class Meta:
        model = GenericAsset

    @validates_schema(skip_on_field_errors=False)
    def validate_name_is_unique_under_parent(self, data, **kwargs):
        if "name" in data:

            asset = db.session.scalars(
                select(GenericAsset)
                .filter_by(
                    name=data["name"],
                    parent_asset_id=data.get("parent_asset_id"),
                    account_id=data.get("account_id"),
                )
                .limit(1)
            ).first()

            if asset:
                raise ValidationError(
                    f"An asset with the name '{data['name']}' already exists under parent asset with id={data.get('parent_asset_id')}.",
                    "name",
                )

    @validates("generic_asset_type_id")
    def validate_generic_asset_type(self, generic_asset_type_id: int):
        generic_asset_type = db.session.get(GenericAssetType, generic_asset_type_id)
        if not generic_asset_type:
            raise ValidationError(
                f"GenericAssetType with id {generic_asset_type_id} doesn't exist."
            )

    @validates("parent_asset_id")
    def validate_parent_asset(self, parent_asset_id: int | None):
        if parent_asset_id is not None:
            parent_asset = db.session.get(GenericAsset, parent_asset_id)
            if not parent_asset:
                raise ValidationError(
                    f"Parent GenericAsset with id {parent_asset_id} doesn't exist."
                )

    @validates("account_id")
    def validate_account(self, account_id: int | None):
        if account_id is None and (
            running_as_cli() or user_has_admin_access(current_user, "update")
        ):
            return
        account = db.session.get(Account, account_id)
        if not account:
            raise ValidationError(f"Account with Id {account_id} doesn't exist.")
        if not running_as_cli() and (
            not user_has_admin_access(current_user, "update")
            and account_id != current_user.account_id
        ):
            raise ValidationError(
                "User is not allowed to create assets for this account."
            )

    @validates("attributes")
    def validate_attributes(self, attributes: dict):
        sensors_to_show = attributes.get("sensors_to_show", [])

        if sensors_to_show:

            # Use SensorsToShowSchema to validate and deserialize sensors_to_show
            sensors_to_show_schema = SensorsToShowSchema()

            standardized_sensors = sensors_to_show_schema.deserialize(sensors_to_show)
            unique_sensor_ids = SensorsToShowSchema.flatten(standardized_sensors)

            # Check whether IDs represent accessible sensors
            from flexmeasures.data.schemas import SensorIdField

            for sensor_id in unique_sensor_ids:
                SensorIdField().deserialize(sensor_id)


class GenericAssetTypeSchema(ma.SQLAlchemySchema):
    """
    GenericAssetType schema, with validations.
    """

    id = ma.auto_field()
    name = fields.Str()
    description = ma.auto_field()

    class Meta:
        model = GenericAssetType


class GenericAssetIdField(MarshmallowClickMixin, fields.Int):
    """Field that deserializes to a GenericAsset and serializes back to an integer."""

    @with_appcontext_if_needed()
    def _deserialize(self, value, attr, obj, **kwargs) -> GenericAsset:
        """Turn a generic asset id into a GenericAsset."""
        generic_asset = db.session.get(GenericAsset, value)
        if generic_asset is None:
            raise FMValidationError(f"No asset found with id {value}.")
        # lazy loading now (asset is somehow not in session after this)
        generic_asset.generic_asset_type
        return generic_asset

    def _serialize(self, asset, attr, data, **kwargs):
        """Turn a GenericAsset into a generic asset id."""
        return asset.id
