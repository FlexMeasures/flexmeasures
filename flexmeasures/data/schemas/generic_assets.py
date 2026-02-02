from __future__ import annotations

from datetime import timedelta
import json
from http import HTTPStatus

from flask import abort
from marshmallow import validates, ValidationError, fields, validates_schema
from marshmallow.validate import OneOf
from flask_security import current_user
from sqlalchemy import select


from flexmeasures.data import ma, db
from flexmeasures.data.models.user import Account
from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.schemas.locations import LatitudeField, LongitudeField
from flexmeasures.data.schemas.sensors import SensorIdField
from flexmeasures.data.schemas.utils import (
    FMValidationError,
    MarshmallowClickMixin,
    extract_sensors_from_flex_config,
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
    a `title` (optional) and a `plots` list, this list then consist of dictionaries with keys such as `sensor`, `asset` or `sensors`.

    - A single sensor ID (int): `42` -> `{"title": None, "plots": [{"sensor": 42}]}`
    - A list of sensor IDs (list of ints): `[42, 43]` -> `{"title": None, "plots": [{"sensors": [42, 43]}]}`
    - A dictionary with a title and sensor: `{"title": "Temperature", "sensor": 42}` -> `{"title": "Temperature", "plots": [{"sensor": 42}]}`
    - A dictionary with a title and sensors: `{"title": "Pressure", "sensors": [42, 43]}` -> `{"title": "Pressure", "plots": [{"sensors": [42, 43]}]}`

    Validation ensures that:
    - The input is either a list, integer, or dictionary.
    - If the input is a dictionary, it must contain either `sensor` (int), `sensors` (list of ints) or `plots` (list of dicts).
    - All sensor IDs must be valid integers.

    Example Inputs:
    - `[{"title": "Test", "plots": [{"sensor": 1}, {"sensor": 2}]}, {"title": "Another Test", "plots": [{"sensors": [3, 4]}]}, 5]`
    - `[{"title": "Test", "sensors": [1, 2]}, {"title": None, "sensors": [3, 4]}, 5]` (Older format but still compatible)

    Example Output (Standardized):
    - `[{"title": "Test", "plots": [{"sensors": [1, 2]}]}, {"title": None, "plots": [{"sensors": [3, 4]}]}, {"title": None, "plots": [{"sensor": 5}]}]`
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
        Normalize various input formats (int, list, or dict) into a standard plot dictionary.
        """
        if isinstance(item, int):
            return {"title": None, "plots": [{"sensor": item}]}
        elif isinstance(item, list):
            if not all(isinstance(sensor_id, int) for sensor_id in item):
                raise ValidationError(
                    "All elements in a list within 'sensors_to_show' must be integers."
                )
            return {"title": None, "plots": [{"sensors": item}]}
        elif isinstance(item, dict):
            return self._standardize_dict_item(item)
        else:
            raise ValidationError(
                "Invalid item type in 'sensors_to_show'. Expected int, list, or dict."
            )

    def _standardize_dict_item(self, item: dict) -> dict:
        """
        Transform a dictionary-based sensor configuration into a standardized 'plots' structure.
        Ensures 'title' is a string and processes 'sensor', 'sensors', or direct 'plots' keys.
        """
        title = "No Title"

        if "title" in item:
            title = item["title"]
            if not isinstance(title, str):
                raise ValidationError("'title' value must be a string.")
        else:
            item["title"] = title

        if "sensor" in item:
            sensor = item["sensor"]
            if not isinstance(sensor, int):
                raise ValidationError("'sensor' value must be an integer.")
            return {"title": title, "plots": [{"sensor": sensor}]}
        elif "sensors" in item:
            sensors = item["sensors"]
            if not isinstance(sensors, list) or not all(
                isinstance(sensor_id, int) for sensor_id in sensors
            ):
                raise ValidationError("'sensors' value must be a list of integers.")
            return {"title": title, "plots": [{"sensors": sensors}]}
        elif "plots" in item:
            plots = item["plots"]
            if not isinstance(plots, list):
                raise ValidationError("'plots' must be a list or dictionary.")
            for plot in plots:
                self._validate_single_plot(plot)

            return {"title": title, "plots": plots}
        else:
            raise ValidationError(
                "Dictionary must contain either 'sensor', 'sensors' or 'plots' key."
            )

    def _validate_single_plot(self, plot):
        """
        Perform structural validation on an individual plot dictionary.
        Requires at least one of: 'sensor', 'sensors', or 'asset'.
        """
        if not isinstance(plot, dict):
            raise ValidationError("Each plot in 'plots' must be a dictionary.")

        if "sensor" not in plot and "sensors" not in plot and "asset" not in plot:
            raise ValidationError(
                "Each plot must contain either 'sensor', 'sensors' or an 'asset' key."
            )

        if "asset" in plot:
            self._validate_asset_in_plot(plot)
        if "sensor" in plot:
            sensor = plot["sensor"]
            if not isinstance(sensor, int):
                raise ValidationError("'sensor' value must be an integer.")
        if "sensors" in plot:
            sensors = plot["sensors"]
            if not isinstance(sensors, list) or not all(
                isinstance(sensor_id, int) for sensor_id in sensors
            ):
                raise ValidationError("'sensors' value must be a list of integers.")

    def _validate_asset_in_plot(self, plot):
        """
        Validate plots that reference a GenericAsset.
        Ensures flex-config schemas are respected when an asset is provided.
        """
        from flexmeasures.data.schemas.scheduling import (
            DBFlexContextSchema,
        )
        from flexmeasures.data.schemas.scheduling.storage import (
            DBStorageFlexModelSchema,
        )

        if "flex-context" not in plot and "flex-model" not in plot:
            raise ValidationError(
                "When 'asset' is provided in a plot, 'flex-context' or 'flex-model' must also be provided."
            )

        self._validate_flex_config_field_is_valid_choice(
            plot, "flex-context", DBFlexContextSchema.mapped_schema_keys.values()
        )
        self._validate_flex_config_field_is_valid_choice(
            plot, "flex-model", DBStorageFlexModelSchema().mapped_schema_keys.values()
        )

    def _validate_flex_config_field_is_valid_choice(
        self, plot_config, field_name, valid_collection
    ):
        """
        Verify that the chosen flex-config field exists on the specific asset and matches
        allowed schema keys.
        """
        if field_name in plot_config:
            value = plot_config[field_name]
            asset_id = plot_config.get("asset")
            asset = GenericAssetIdField().deserialize(asset_id)

            if asset is None:
                raise ValidationError(f"Asset with ID {asset_id} does not exist.")

            if value and not isinstance(value, str):
                raise ValidationError(f"The value for '{field_name}' must be a string.")

            if value not in valid_collection:
                raise ValidationError(f"'{field_name}' value '{value}' is not valid.")

            attr_to_check = (
                "flex_model" if field_name == "flex-model" else "flex_context"
            )
            asset_flex_config = getattr(asset, attr_to_check, {})

            if value not in asset_flex_config:
                raise ValidationError(
                    f"The asset with ID '{asset_id}' does not have a '{value}' set in its '{attr_to_check}'."
                )

    @classmethod
    def flatten(cls, nested_list) -> list[int]:
        """
        Flatten a nested list of sensors or sensor dictionaries into a unique list of sensor IDs.

        This method processes the following formats, for each of the entries of the nested list:
        - A list of sensor IDs: `[1, 2, 3]`
        - A list of dictionaries where each dictionary contains a `sensors` list, a `sensor` key or a `plots` key
        `[{"title": "Temperature", "sensors": [1, 2]}, {"title": "Pressure", "sensor": 3},  {"title": "Pressure", "plots": [{"sensor": 4}, {"sensors": [5,6]}]}]`
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
            elif isinstance(s, int):
                all_objects.append(s)
            elif isinstance(s, dict):
                if "plots" in s:
                    for plot in s["plots"]:
                        if "sensors" in plot:
                            all_objects.extend(plot["sensors"])
                        if "sensor" in plot:
                            all_objects.append(plot["sensor"])
                        if "asset" in plot:
                            sensors = extract_sensors_from_flex_config(plot)
                            all_objects.extend(sensors)
                elif "sensors" in s:
                    all_objects.extend(s["sensors"])
                elif "sensor" in s:
                    all_objects.append(s["sensor"])

        return list(dict.fromkeys(all_objects).keys())


class SensorKPIFieldSchema(ma.SQLAlchemySchema):
    title = fields.Str(required=True)
    sensor = SensorIdField(required=True)
    function = fields.Str(required=False, validate=OneOf(["sum", "min", "max", "mean"]))

    @validates("sensor")
    def validate_sensor(self, value, **kwargs):
        if value.event_resolution != timedelta(days=1):
            raise ValidationError(f"Sensor with ID {value} is not a daily sensor.")
        return value


class SensorsToShowAsKPIsSchema(ma.SQLAlchemySchema):
    sensors_to_show_as_kpis = fields.List(
        fields.Nested(SensorKPIFieldSchema), required=True
    )


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
    sensors_to_show = JSON(required=False)
    flex_context = JSON(required=False)
    flex_model = JSON(required=False)
    sensors_to_show_as_kpis = JSON(required=False)
    external_id = fields.Str(
        required=False,
        metadata=dict(
            description="ID for this asset in another system.",
            example="c8a53865-4702-494d-b559-9eefce296038",
        ),
    )

    class Meta:
        model = GenericAsset

    @validates_schema(skip_on_field_errors=False)
    def validate_name_is_unique_under_parent(self, data, **kwargs):
        """
        Validate that name is unique among siblings.
        This is also checked by a db constraint.
        Here, we can only check if we have all information (a full form),
        which usually is at creation time.
        """
        if "name" in data and "parent_asset_id" in data:
            asset = db.session.scalars(
                select(GenericAsset)
                .filter_by(
                    name=data["name"],
                    parent_asset_id=data.get("parent_asset_id"),
                )
                .limit(1)
            ).first()

            if asset:
                err_msg = f"An asset with the name '{data['name']}' already exists under parent asset {data.get('parent_asset_id')}"
                raise ValidationError(err_msg, "name")

    @validates("generic_asset_type_id")
    def validate_generic_asset_type(self, generic_asset_type_id: int, **kwargs):
        generic_asset_type = db.session.get(GenericAssetType, generic_asset_type_id)
        if not generic_asset_type:
            raise ValidationError(
                f"GenericAssetType with id {generic_asset_type_id} doesn't exist."
            )

    @validates("parent_asset_id")
    def validate_parent_asset(self, parent_asset_id: int | None, **kwargs):
        if parent_asset_id is not None:
            parent_asset = db.session.get(GenericAsset, parent_asset_id)
            if not parent_asset:
                raise ValidationError(
                    f"Parent GenericAsset with id {parent_asset_id} doesn't exist."
                )

    @validates("account_id")
    def validate_account(self, account_id: int | None, **kwargs):
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
    def validate_attributes(self, attributes: dict, **kwargs):
        """
        Validate sensors_to_show if sent within attributes.
        Deprecated, as this is now its own field on the model.
        Can be deleted once we stop supporting storing them under here.
        """
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

    def __init__(self, status_if_not_found: HTTPStatus | None = None, *args, **kwargs):
        self.status_if_not_found = status_if_not_found
        super().__init__(*args, **kwargs)

    def _deserialize(self, value: int | str, attr, obj, **kwargs) -> GenericAsset:
        """Turn a generic asset id into a GenericAsset."""
        generic_asset: GenericAsset = db.session.execute(
            select(GenericAsset).filter_by(id=int(value))
        ).scalar_one_or_none()
        if generic_asset is None:
            message = f"No asset found with ID {value}."
            if self.status_if_not_found == HTTPStatus.NOT_FOUND:
                raise abort(404, message)
            else:
                raise FMValidationError(message)

        return generic_asset

    def _serialize(self, asset: GenericAsset, attr, data, **kwargs) -> int:
        """Turn a GenericAsset into a generic asset id."""
        return asset.id if asset else None
