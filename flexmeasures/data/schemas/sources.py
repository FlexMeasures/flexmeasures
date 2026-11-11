from flask import current_app
from marshmallow import ValidationError, fields

from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.schemas.utils import (
    get_by_id,
    with_appcontext_if_needed,
    FMValidationError,
    MarshmallowClickMixin,
)


class DataSourceIdField(MarshmallowClickMixin, fields.Int):
    """Field that deserializes to a DataSource and serializes back to an integer."""

    @with_appcontext_if_needed()
    def _deserialize(self, value, attr, obj, **kwargs) -> DataSource:
        """Turn a source id into a DataSource."""
        value = super()._deserialize(value, attr, obj, **kwargs)
        source = get_by_id(DataSource, value)
        if source is None:
            raise FMValidationError(f"No data source found with id {value}.")
        return source

    def _serialize(self, source, attr, data, **kwargs):
        """Turn a DataSource into a source id."""
        return source.id


def validate_data_generator_kind(value: str):
    """Check that a kind of data generator is registered, such as forecaster, reporter or scheduler, or one that a plugin adds."""
    generator_kinds = sorted(current_app.data_generators)
    if value not in generator_kinds:
        raise ValidationError(
            f"Unknown kind of data generator '{value}'. Choose one of: {', '.join(generator_kinds)}."
        )
