from flask_security import current_user
from marshmallow import (
    Schema,
    ValidationError,
    fields,
    post_load,
    validates,
)
from pandas.api.types import is_numeric_dtype
import pandas as pd
import timely_beliefs as tb
from werkzeug.datastructures import FileStorage

from flexmeasures.data import ma
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.schemas.utils import (
    FMValidationError,
    MarshmallowClickMixin,
    with_appcontext_if_needed,
)
from flexmeasures.utils.unit_utils import is_valid_unit


class SensorSchemaMixin(Schema):
    """
    Base sensor schema.

    Here we include all fields which are implemented by timely_beliefs.SensorDBMixin
    All classes inheriting from timely beliefs sensor don't need to repeat these.
    In a while, this schema can represent our unified Sensor class.

    When subclassing, also subclass from `ma.SQLAlchemySchema` and add your own DB model class, e.g.:

        class Meta:
            model = Asset
    """

    name = ma.auto_field(required=True)
    unit = ma.auto_field(required=True)
    timezone = ma.auto_field()
    event_resolution = fields.TimeDelta(required=True, precision="minutes")
    entity_address = fields.String(dump_only=True)

    @validates("unit")
    def validate_unit(self, unit: str):
        if not is_valid_unit(unit):
            raise ValidationError(f"Unit '{unit}' cannot be handled.")


class SensorSchema(SensorSchemaMixin, ma.SQLAlchemySchema):
    """
    Sensor schema, with validations.
    """

    generic_asset_id = fields.Integer(required=True)

    @validates("generic_asset_id")
    def validate_generic_asset(self, generic_asset_id: int):
        generic_asset = GenericAsset.query.get(generic_asset_id)
        if not generic_asset:
            raise ValidationError(
                f"Generic asset with id {generic_asset_id} doesn't exist."
            )

    class Meta:
        model = Sensor


class SensorIdField(MarshmallowClickMixin, fields.Int):
    """Field that deserializes to a Sensor and serializes back to an integer."""

    @with_appcontext_if_needed()
    def _deserialize(self, value: int, attr, obj, **kwargs) -> Sensor:
        """Turn a sensor id into a Sensor."""
        sensor = Sensor.query.get(value)
        if sensor is None:
            raise FMValidationError(f"No sensor found with id {value}.")
        # lazy loading now (sensor is somehow not in session after this)
        sensor.generic_asset
        return sensor

    def _serialize(self, sensor: Sensor, attr, data, **kwargs) -> int:
        """Turn a Sensor into a sensor id."""
        return sensor.id


class SensorDataFileSchema(Schema):
    uploaded_files = fields.List(
        fields.Field(metadata={"type": "string", "format": "byte"}),
        data_key="uploaded-files",
    )
    sensor = SensorIdField(data_key="id")

    _valid_content_types = {"text/csv", "text/plain", "text/x-csv"}

    @validates("uploaded_files")
    def validate_uploaded_files(self, files: list[FileStorage]):
        """Validate the deserialized fields."""
        errors = {}
        for i, file in enumerate(files):
            file_errors = []
            if not isinstance(file, FileStorage):
                file_errors += [
                    f"Invalid content: {file}. Only CSV files are accepted."
                ]
            if file.filename == "":
                file_errors += ["Filename is missing."]
            elif file.filename[-4:].lower() != ".csv":
                file_errors += [
                    f"Invalid filename: {file.filename}. File extension should be '.csv'."
                ]
            if file.content_type not in self._valid_content_types:
                file_errors += [
                    f"Invalid content type: {file.content_type}. Only the following content types are accepted: {self._valid_content_types}."
                ]
            if file_errors:
                errors[i] = file_errors
        if errors:
            raise ValidationError(errors)

    @post_load
    def post_load(self, fields, **kwargs):
        """Process the deserialized and validated fields.

        Remove the 'sensor' and 'files' fields, and add the 'data' field containing a list of BeliefsDataFrames.
        """
        sensor = fields.pop("sensor")
        dfs = []
        files: list[FileStorage] = fields.pop("uploaded_files")
        errors = {}
        for i, file in enumerate(files):
            try:
                df = tb.read_csv(
                    file,
                    sensor,
                    source=current_user.data_source[0],
                    belief_time=pd.Timestamp.utcnow(),
                    resample=True,
                )
                assert is_numeric_dtype(
                    df["event_value"]
                ), "event values should be numeric"
                dfs.append(df)
            except Exception as e:
                errors[
                    i
                ] = f"Invalid content in file: {file.filename}. Failed with: {str(e)}"
        if errors:
            raise ValidationError(errors)
        fields["data"] = dfs
        return fields
